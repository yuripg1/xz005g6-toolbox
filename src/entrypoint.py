#!/usr/bin/env python3
"""
XZ005-G6 Toolbox — Docker entrypoint.

Modes:
  build  [FIRMWARE.bin]  Extract, patch, rebuild SquashFS, generate commands.
  config [CONF.bin]      Decrypt config, set AdminEnable=1, re-encrypt.
  serve                  Start atftpd on TFTP_PORT serving output/.

If no file is given, the first .bin in firmware/ or config/ is used.
"""

import glob
import os
import subprocess
import sys
import shutil
import hashlib


ROOTFS_DIR = '/tmp/rootfs'
TPCONF = '/opt/tpconf_bin_xml/tpconf_bin_xml.py'


def run(cmd, check=True):
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            print(f"    {line}")
    if check and result.returncode != 0:
        print(f"  ERROR: {result.stderr}")
        sys.exit(1)
    return result


def find_bin(directory, label):
    bins = sorted(glob.glob(f'{directory}/*.bin'))
    if not bins:
        print(f"ERROR: No .bin file found in {directory}/")
        print(f"Place your {label} file there and try again.")
        sys.exit(1)
    if len(bins) > 1:
        print(f"Found {len(bins)} .bin files in {directory}/, using {os.path.basename(bins[0])}")
    return bins[0]


def mode_build(firmware_path=None):
    if firmware_path is None:
        firmware_path = find_bin('/work/firmware', 'firmware')
    if not os.path.exists(firmware_path):
        print(f"ERROR: {firmware_path} not found.")
        sys.exit(1)

    bdp_value = os.environ.get('BDP_VALUE', '136')
    dual_value = os.environ.get('DUAL_MGMT_VALUE', '1')
    extra = os.environ.get('EXTRA_FLASH_COMMANDS', '')

    print(f"=== Stage 1: Extract SquashFS from {os.path.basename(firmware_path)} ===")
    run(f'binwalk -e -q --run-as=root --directory=/tmp/extracted "{firmware_path}"')

    sq_path = None
    for root, dirs, files in os.walk('/tmp/extracted'):
        for f in files:
            if f.endswith('.squashfs'):
                sq_path = os.path.join(root, f)
                break
        if sq_path:
            break

    if not sq_path:
        print("ERROR: Could not find SquashFS in extracted firmware.")
        sys.exit(1)
    print(f"  Found: {sq_path}")

    print("\n=== Stage 2: Extract root filesystem ===")
    if os.path.exists(ROOTFS_DIR):
        shutil.rmtree(ROOTFS_DIR)
    run(f'unsquashfs -d {ROOTFS_DIR} "{sq_path}"')

    print("\n=== Stage 3: Patch files ===")
    # 3a. config_xmlconfig.sh — replace the flash set line, add DUAL_MGMT_MODE and extras
    script_path = f'{ROOTFS_DIR}/etc/scripts/config_xmlconfig.sh'
    with open(script_path, 'r') as f:
        content = f.read()

    # Build the replacement block
    lines = []
    lines.append(f'flash set OMCI_CUSTOM_BDP {bdp_value}')
    lines.append(f'echo "Set OMCI_CUSTOM_BDP {bdp_value}"')
    lines.append(f'flash set DUAL_MGMT_MODE {dual_value}')
    lines.append(f'echo "Set DUAL_MGMT_MODE {dual_value}"')
    if extra:
        lines.append(extra)

    replacement = '\n\t\t\t\t'.join(lines)
    content = content.replace(
        'flash set OMCI_CUSTOM_BDP 2\n\t\t\t\techo "Set OMCI_CUSTOM_BDP 2"',
        replacement
    )

    with open(script_path, 'w') as f:
        f.write(content)
    run(f'grep -n "OMCI_CUSTOM_BDP\|DUAL_MGMT_MODE" {script_path}')

    # 3b. config_default.xml (ROT-1 encoded)
    xml_path = f'{ROOTFS_DIR}/etc/config_default.xml'
    with open(xml_path, 'rb') as f:
        xml = f.read()
    decoded = bytes((b - 1) & 0xFF for b in xml).decode('utf-8', errors='replace')
    decoded = decoded.replace(
        'OMCI_CUSTOM_BDP" Value="2"',
        f'OMCI_CUSTOM_BDP" Value="{bdp_value}"'
    )
    decoded = decoded.replace(
        'DUAL_MGMT_MODE" Value="0"',
        f'DUAL_MGMT_MODE" Value="{dual_value}"'
    )
    reencoded = bytes((b + 1) & 0xFF for b in decoded.encode('utf-8'))
    with open(xml_path, 'wb') as f:
        f.write(reencoded)
    print(f"  config_default.xml: BDP={bdp_value}, DUAL_MGMT_MODE={dual_value}")

    # 3c. runsdk.sh
    sdk_path = f'{ROOTFS_DIR}/etc/runsdk.sh'
    with open(sdk_path, 'r') as f:
        content = f.read()
    content = content.replace('#/bin/pondetect &', '/bin/pondetect &')
    with open(sdk_path, 'w') as f:
        f.write(content)
    run(f'grep -n "pondetect" {sdk_path}')

    print("\n=== Stage 4: Rebuild SquashFS ===")
    output_path = '/work/output/patched_rootfs.squashfs'
    os.makedirs('/work/output', exist_ok=True)
    run(f'mksquashfs {ROOTFS_DIR} "{output_path}" '
        f'-comp lzma -b 1048576 -noappend -always-use-fragments -no-xattrs -all-root')

    size = os.path.getsize(output_path)
    with open(output_path, 'rb') as f:
        md5 = hashlib.md5(f.read()).hexdigest()

    info = subprocess.run(['unsquashfs', '-s', output_path],
                          capture_output=True, text=True)
    inode_line = [l for l in info.stdout.split('\n') if 'inodes' in l.lower()]
    dev_count = subprocess.run(
        f"unsquashfs -ll '{output_path}' | grep -c '^[cb]'",
        shell=True, capture_output=True, text=True)
    sym_count = subprocess.run(
        f"unsquashfs -ll '{output_path}' | grep -c '^l'",
        shell=True, capture_output=True, text=True)

    print(f"\n=== Validation ===")
    print(f"  Size:         {size} bytes (must be <= 2523136)")
    print(f"  MD5:          {md5}")
    if inode_line:
        print(f"  {inode_line[0].strip()}")
    print(f"  Device nodes: {dev_count.stdout.strip()} (must be 238)")
    print(f"  Symlinks:     {sym_count.stdout.strip()} (must be 126)")

    if size > 2523136:
        print("ERROR: SquashFS too large for MTD5 partition!")
        sys.exit(1)

    print(f"\n=== Stage 5: Generate sys commands ===")
    env = os.environ.copy()
    env['COMMANDS_FILE'] = '/opt/patcher/commands.txt'
    env['OUTPUT_FILE'] = '/work/output/COMMANDS.txt'
    subprocess.run([sys.executable, '/opt/patcher/encrypt.py'], env=env)

    print(f"\nDone. Artifacts in output/:")
    print(f"  patched_rootfs.squashfs  ({size} bytes, MD5: {md5})")
    print(f"  COMMANDS.txt")
    print(f"\n  When verifying with check_md5, expect: {md5}")


def mode_config(config_path=None):
    if config_path is None:
        config_path = find_bin('/work/config', 'config backup')

    if not os.path.exists(config_path):
        print(f"ERROR: {config_path} not found.")
        sys.exit(1)

    os.makedirs('/work/output', exist_ok=True)
    xml_path = '/tmp/config.xml'
    modified_xml = '/tmp/config_admin.xml'
    output_bin = '/work/output/conf_admin.bin'

    print(f"=== Decrypt config backup: {os.path.basename(config_path)} ===")
    run(f'python3 {TPCONF} "{config_path}" {xml_path}')

    print("=== Set AdminEnable=1 ===")
    with open(xml_path, 'r') as f:
        content = f.read()
    if 'AdminEnable val=0' in content:
        content = content.replace('AdminEnable val=0', 'AdminEnable val=1')
        with open(modified_xml, 'w') as f:
            f.write(content)
        print("  Changed: AdminEnable val=0 -> val=1")
    elif 'AdminEnable val=1' in content:
        shutil.copy(xml_path, modified_xml)
        print("  Already AdminEnable val=1, no change needed")
    else:
        print("  WARNING: AdminEnable tag not found!")
        shutil.copy(xml_path, modified_xml)

    print("=== Re-encrypt config ===")
    run(f'python3 {TPCONF} {modified_xml} "{output_bin}"')

    print(f"\nDone. Output: {output_bin}")
    print("Import this file via the web UI (System Tools > Backup & Restore).")


def mode_serve():
    port = os.environ.get('TFTP_PORT', '6969')
    serve_dir = '/work/output'
    os.makedirs(serve_dir, exist_ok=True)

    if not os.path.exists(f'{serve_dir}/patched_rootfs.squashfs'):
        print(f"WARNING: patched_rootfs.squashfs not found in {serve_dir}")
        print("Run 'build' mode first or place the file manually.")

    print(f"Serving {serve_dir} on UDP port {port}...")
    print("Press Ctrl+C to stop.")
    try:
        run(f'atftpd --daemon --no-fork --port {port} {serve_dir}', check=False)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: docker run ... xz005g6-toolbox <mode> [file]")
        print("  build             — Build patched SquashFS (auto-discovers firmware/*.bin)")
        print("  build FILE.bin    — Build from a specific file")
        print("  config            — Enable admin in config backup (auto-discovers config/*.bin)")
        print("  config FILE.bin   — Process a specific config file")
        print("  serve             — Start TFTP server")
        sys.exit(1)

    mode = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if mode == 'build':
        mode_build(arg)
    elif mode == 'config':
        mode_config(arg)
    elif mode == 'serve':
        mode_serve()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
