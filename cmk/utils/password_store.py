#!/usr/bin/env python3
# Copyright (C) 2019 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.
"""This module is meant to be used by components (e.g. active checks, notifications, bakelets)
that support getting credentials from the Check_MK password store.

The password stores primary use is to centralize stored credentials. Instead of spreading the
credentials in the whole configuration, we have this as a central place for sensitive information.

The password store mechanic provides a mechanism for keeping passwords out of the cmdline of a
process, e.g. an active check plugin. It has been built to extend existing plugins with as small
modificiations as possible. It is built out of two parts:

a) Adding arguments for the command line. This job is done for active checks plugins by
   `cmk.base.core_config._prepare_check_command` and `cmk.base.check_api.passwordstore_get_cmdline`.

b) Extracting arguments from the command line. This is done by `password_store.replace_passwords`
   for python plugins and for C monitoring plugins by the patches which can be found at
   `omd/packages/monitoring-plugins/patches/0003-cmk-password-store.dif`.

   The most interesting part is, that the password store arguments are replaced before the existing
   argument handling of the active check plugins is executed. This way we don't have to deal with
   the individual mechanics of the active check plugins. We can hook into the entry point of the
   plugin, do our work and leave the rest to the plugin.

Python active check plugins need to do something like this before the argv are processed.

  import cmk.utils.password_store
  cmk.utils.password_store.replace_passwords()

  (... use regular argv processing ...)

For cases where the password ID is not received from the command line, for example a configuration
file, there is the `extract` function which can be used like this:

  import cmk.utils.password_store
  password = cmk.utils.password_store.extract("pw_id")

"""
import os
import sys
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Literal, NoReturn

from typing_extensions import TypedDict

import cmk.utils.paths
import cmk.utils.store as store
from cmk.utils.config_path import ConfigPath, LATEST_CONFIG
from cmk.utils.crypto.secrets import PasswordStoreSecret
from cmk.utils.crypto.symmetric import aes_gcm_decrypt, aes_gcm_encrypt, TaggedCiphertext
from cmk.utils.exceptions import MKGeneralException

PasswordLookupType = Literal["password", "store"]
PasswordId = str | tuple[PasswordLookupType, str]


class Password(TypedDict):
    title: str
    comment: str
    docu_url: str
    password: str
    # Only owners can edit the password
    # None -> Administrators (having the permission "Write access to all passwords")
    # str -> Name of the contact group owning the password
    owned_by: str | None
    shared_with: list[str]


def password_store_path() -> Path:
    return Path(cmk.utils.paths.var_dir, "stored_passwords")


def bail_out(s: str) -> NoReturn:
    sys.stdout.write("UNKNOWN - %s\n" % s)
    sys.stderr.write("UNKNOWN - %s\n" % s)
    sys.exit(3)


def replace_passwords() -> None:
    if len(sys.argv) < 2:
        return  # command line too short

    if not [a for a in sys.argv if a.startswith("--pwstore")]:
        return  # no password store in use

    # --pwstore=4@4@web,6@0@foo
    #  In the 4th argument at char 4 replace the following bytes
    #  with the passwords stored under the ID 'web'
    #  In the 6th argument at char 0 insert the password with the ID 'foo'

    # Extract first argument and parse it

    pwstore_args = sys.argv.pop(1).split("=", 1)[1]
    passwords = load_for_helpers()

    for password_spec in pwstore_args.split(","):
        parts = password_spec.split("@")
        if len(parts) != 3:
            bail_out(f"pwstore: Invalid --pwstore entry: {password_spec}")

        try:
            num_arg, pos_in_arg, password_id = int(parts[0]), int(parts[1]), parts[2]
        except ValueError:
            bail_out(f"pwstore: Invalid format: {password_spec}")

        try:
            arg = sys.argv[num_arg]
        except IndexError:
            bail_out("pwstore: Argument %d does not exist" % num_arg)

        try:
            password = passwords[password_id]
        except KeyError:
            bail_out(f"pwstore: Password '{password_id}' does not exist")

        sys.argv[num_arg] = arg[:pos_in_arg] + password + arg[pos_in_arg + len(password) :]


def save(passwords: Mapping[str, str], store_path: Path) -> None:
    """Save the passwords to the pre-activation path"""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    content = ""
    for ident, pw in passwords.items():
        # This is normally needed to not break the file format for things like gcp tokens.
        # The GUI does this automatically by having only one line of input field,
        # but other sources (like the REST API) use this function as well.
        password_on_one_line = pw.replace("\n", "")
        content += f"{ident}:{password_on_one_line}\n"

    store.save_bytes_to_file(store_path, PasswordStore.encrypt(content))


def load() -> dict[str, str]:
    return _load(password_store_path())


def _load(store_path: Path) -> dict[str, str]:
    passwords: dict[str, str] = {}
    with suppress(FileNotFoundError):
        store_path_bytes: bytes = store_path.read_bytes()
        if not store_path_bytes:
            return passwords
        for line in PasswordStore.decrypt(store_path_bytes).splitlines():
            ident, password = line.strip().split(":", 1)
            passwords[ident] = password

    return passwords


def extract(password_id: PasswordId) -> str | None:
    """Translate the password store reference to the actual password"""
    if not isinstance(password_id, tuple):
        return load().get(password_id)

    # In case we get a tuple, assume it was coming from a ValueSpec "IndividualOrStoredPassword"
    pw_type, pw_id = password_id
    if pw_type == "password":
        return pw_id
    if pw_type == "store":
        # TODO: Is this None really intended? Shouldn't we better raise an exception?
        return load().get(pw_id)

    raise MKGeneralException("Unknown password type.")


def save_for_helpers(config_base_path: ConfigPath, passwords: Mapping[str, str]) -> None:
    """Update the helper password store with the given passwords"""
    save(passwords, _helper_password_store_path(config_base_path))


def load_for_helpers() -> dict[str, str]:
    return _load(_helper_password_store_path(LATEST_CONFIG))


def _helper_password_store_path(config_path: ConfigPath) -> Path:
    return Path(config_path) / "stored_passwords"


class PasswordStore:
    VERSION = 0
    VERSION_BYTE_LENGTH = 2

    SALT_LENGTH: int = 16
    NONCE_LENGTH: int = 16

    @staticmethod
    def encrypt(value: str) -> bytes:
        salt = os.urandom(PasswordStore.SALT_LENGTH)
        nonce = os.urandom(PasswordStore.NONCE_LENGTH)
        key = PasswordStoreSecret().derive_secret_key(salt)
        encrypted = aes_gcm_encrypt(key, nonce, value)
        return (
            PasswordStore.VERSION.to_bytes(PasswordStore.VERSION_BYTE_LENGTH, byteorder="big")
            + salt
            + nonce
            + encrypted.tag
            + encrypted.ciphertext
        )

    @staticmethod
    def decrypt(raw: bytes) -> str:
        _version, rest = (  # noqa: F841
            raw[: PasswordStore.VERSION_BYTE_LENGTH],
            raw[PasswordStore.VERSION_BYTE_LENGTH :],
        )
        salt, rest = rest[: PasswordStore.SALT_LENGTH], rest[PasswordStore.SALT_LENGTH :]
        nonce, rest = rest[: PasswordStore.NONCE_LENGTH], rest[PasswordStore.NONCE_LENGTH :]
        tag, encrypted = rest[: TaggedCiphertext.TAG_LENGTH], rest[TaggedCiphertext.TAG_LENGTH :]
        key = PasswordStoreSecret().derive_secret_key(salt)
        return aes_gcm_decrypt(key, nonce, TaggedCiphertext(ciphertext=encrypted, tag=tag))
