#!/usr/bin/env python3
"""
Read plaintext sys commands and encrypt them for the device.
Outputs COMMANDS.txt ready to paste into telnet.
Comment lines (starting with #) and blank lines are passed through.
"""

import base64
import os
import sys

from Cryptodome.Cipher import DES


def pad(data: bytes) -> bytes:
    n = len(data) % 8
    if n:
        data += b'\x00' * (8 - n)
    return data


def encrypt(plaintext: str, key: bytes) -> str:
    cipher = DES.new(key, DES.MODE_ECB)
    return base64.b64encode(cipher.encrypt(pad(plaintext.encode()))).decode()


def main():
    product_id = os.environ.get('X_TP_PRODUCT_ID', '477720065')
    base_key_hex = os.environ.get('BASE_KEY', '478DE3F90BA5D2CF')
    host_ip = os.environ.get('HOST_IP', '192.168.1.2')
    tftp_port = os.environ.get('TFTP_PORT', '6969')
    commands_file = os.environ.get('COMMANDS_FILE', 'commands.txt')
    output_file = os.environ.get('OUTPUT_FILE', 'COMMANDS.txt')

    base_key = bytes.fromhex(base_key_hex)
    mask = product_id.encode()[:8]
    derived_key = bytes(a ^ b for a, b in zip(base_key, mask))

    try:
        with open(commands_file, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"ERROR: {commands_file} not found", file=sys.stderr)
        sys.exit(1)

    with open(output_file, 'w') as out:
        out.write("# XZ005-G6 sys commands — paste into telnet at TP-Link(conf)#\n")
        out.write(f"# Generated for ProductID={product_id}\n\n")

        for line in lines:
            stripped = line.strip()

            # Pass through blank lines and comment-only lines
            if not stripped or stripped.startswith('#'):
                out.write(line)
                continue

            if '|' not in stripped:
                continue

            label, cmd = stripped.split('|', 1)
            label = label.strip()
            cmd = cmd.strip()

            cmd = cmd.replace('__HOST_IP__', host_ip)
            cmd = cmd.replace('__TFTP_PORT__', tftp_port)

            encrypted = encrypt(cmd, derived_key)

            out.write(f"# {label}\n")
            out.write(f"sys {encrypted}\n\n")

    print(f"Wrote {output_file}")


if __name__ == '__main__':
    main()
