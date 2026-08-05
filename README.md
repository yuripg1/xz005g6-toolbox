# XZ005-G6 Toolbox

Permanently fix the TP-Link XZ005-G6 GPON ONU (Realtek RTL9602C) so it passes
data with ISPs whose OLTs do not send complete OMCI VLAN provisioning — most
notably Vivo Brazil (Huawei OLT, Region 2).

Tested with firmware version `0.2.0 3.0.0 v6066.0 Build 250711 Rel.74023n`,
restoring the behavior of `0.1.0 3.0.0 v6066.0 Build 231212 Rel.36338n`.

---

## The Problem

The XZ005-G6 reaches GPON state O5 (fully authenticated and ranged) but no
user data flows. PPPoE does not connect. No packets pass.

Firmware v0.2.0 changed `OMCI_CUSTOM_BDP` from 136 to 2, disabling two
userspace VLAN workaround modules that create synthetic bridge forwarding
rules when the OLT does not send them via OMCI. The boot script force-
overwrites this value to 2 on every boot, which is why downgrading firmware
and factory reset do not help.

## The Fix

Three changes to the SquashFS root filesystem, all reverting v0.2.0 behavior
back to the v0.1.0 defaults:

1. **`OMCI_CUSTOM_BDP`**: boot script changed from `flash set ... 2` to
   `flash set ... 136`. Enables the two userspace VLAN workaround modules
   (`bdp_00000080.so` and `bdp_00000008.so`) that generate pass-through
   bridge forwarding rules when the OLT does not send complete VLAN
   provisioning via OMCI. The compiled MIB default remains 2, so the
   `flash set` override is necessary — the XML default alone is insufficient
   because `xmlconfig -def_mib` sets the value from compiled code before
   the XML is processed.

2. **`DUAL_MGMT_MODE`**: changed from 0 to 1 in `config_default.xml`.
   Restores the work-queue OMCI message processing mode. Unlike BDP,
   this value has no compiled default, so the XML change alone is sufficient.

3. **`pondetect`**: re-enabled in `runsdk.sh` (v0.2.0 commented it out).
   This daemon auto-detects the PON mode (GPON vs EPON) from the optical
   hardware state and can reset the CDR (Clock Data Recovery) circuit if
   the receiver loses synchronization. Not essential for data flow, but
   restores a v0.1.0 safety net.

The patched rootfs is written directly to the MTD flash partition (`/dev/mtd5`),
bypassing the RSA signature check that blocks modified firmware through the
web UI upgrade path.

## How To Use

### Requirements

- Docker (Linux, macOS, or Windows with WSL2/Docker Desktop)
- The firmware file `XZ005-G6v1_0.2.0_3.0.0_UP_BOOT(250711)_2025-07-13_18.25.08.bin`
  (obtain from TP-Link's support website for your region)
- An Ethernet cable to connect your computer directly to the modem
- Internet access during Stages 1–2 (for Docker build and Git clone)

### Stage 1 — Build the Patched SquashFS

Place the firmware `.bin` file in the `firmware/` directory, then run:

```shell
$ docker build -t xz005g6-toolbox .
$ docker run --rm -v "$(pwd):/work" xz005g6-toolbox build "/work/firmware/XZ005-G6v1_0.2.0_3.0.0_UP_BOOT(250711)_2025-07-13_18.25.08.bin"
```

This produces two files in `output/`:

- `patched_rootfs.squashfs` — the patched root filesystem (≈2.4 MB)
- `COMMANDS.txt` — all `sys` commands ready to paste into telnet

### Stage 2 — Enable Admin Access

The telnet CLI requires `AdminEnable=1` to reach the `TP-Link(conf)#` prompt
where the `sys` command is available.

1. Open `http://192.168.1.1` in a browser. Set a user password when prompted.
2. Go to **System Tools > Backup & Restore**. Click **Backup** to download
   your config file (usually `conf.bin`).
3. Place the downloaded file in the `firmware/` directory and run:

   ```shell
   $ docker run --rm -v "$(pwd):/work" xz005g6-toolbox config /work/firmware/conf.bin
   ```

   This produces `output/admin_config.bin`.
4. In the web UI, click **Restore** and select `admin_config.bin`. The modem
   reboots.
5. After reboot, visit `http://192.168.1.1/superadmin`. Set a superadmin
   password. Verify you can log in. This confirms the admin config is active.

### Stage 3 — Flash the Fix

#### 3a. Prepare the direct connection

Disconnect your computer from your home network. Connect the computer directly
to the modem's Ethernet port with a cable. Configure a static IP:

- **Linux**: `sudo ip addr add 192.168.1.2/24 dev eth0`
- **macOS**: System Settings > Network > Ethernet > Configure IPv4 > Manually,
  set IP `192.168.1.2`, subnet `255.255.255.0`
- **Windows**: Control Panel > Network and Sharing Center > Change adapter
  settings > Right-click Ethernet > Properties > IPv4 > Use the following IP
  address: `192.168.1.2`, mask `255.255.255.0`

#### 3b. Start the TFTP server (Terminal 2)

```shell
$ docker run --rm -p 6969:6969/udp -v "$(pwd):/work" xz005g6-toolbox serve
```

Leave this running. It serves `output/patched_rootfs.squashfs` to the modem.

#### 3c. Telnet and run the commands (Terminal 1)

Open `COMMANDS.txt` from the `output/` directory. It contains ready-to-paste
`sys` commands with comments explaining what each does.

```shell
$ telnet 192.168.1.1
```

At the `TP-Link(conf)#` prompt, paste each `sys` command in order:

| Step | What it does | Expected output |
|------|-------------|-----------------|
| `warmup` | Initializes encryption state | (silent) |
| `tftp_get` | Downloads patched SquashFS to `/tmp` | (silent — takes 5–15s) |
| `check_size` | Verifies file size is 2408448 | `-rw-r--r-- ... 2408448 ...` |
| `check_md5` | Verifies file integrity | MD5 must match build output |
| `backup` | Saves current rootfs (optional) | (silent) |
| `erase` | Erases the flash partition | `Erasing ... 99%` |
| `write` | Writes patched SquashFS | (silent — takes 2–3s) |
| `verify` | Byte-by-byte comparison | `cmp: EOF on /tmp/new.squashfs` |
| `reboot` | Reboots the modem | (telnet disconnects) |

**Important**: The `sys` command is only available for 10 minutes after boot.
The sequence above takes about 2 minutes. If you exceed the window, reboot the
modem and start again.

**Critical**: Do not reboot until `verify` shows `EOF on /tmp/new.squashfs`.
This message means every byte matches — the flash is bit-perfect. If you see
`differ: char N` instead, go back to `erase` and `write` and try again.

#### 3d. Verify the fix

Wait 30–60 seconds after reboot, then telnet back in:

```
telnet 192.168.1.1
sys nF0fadtl3r4=
sys <check_bdp>     # should show BDP: 0x00000088
sys <check_omci>    # should show OMCI_CUSTOM_BDP=136
sys <check_dual>    # should show DUAL_MGMT_MODE=1
```

Connect your router. PPPoE should connect and internet should work within
30–60 seconds of the modem reaching O5.

The fix is permanent — survives reboots, power cycles, and factory resets.

## Configuration

All tunable values are in `.env`. Defaults work for Vivo Brazil Region 2.

| Variable | Default | Purpose |
|----------|---------|---------|
| `X_TP_PRODUCT_ID` | `477720065` | Device identity for `sys` encryption. Change for other Realtek models. |
| `BASE_KEY` | `478DE3F90BA5D2CF` | Hardcoded DES key. Unlikely to need changing. |
| `DEVICE_IP` | `192.168.1.1` | Modem IP during direct-connect flash. |
| `HOST_IP` | `192.168.1.2` | Your computer's IP during direct-connect flash. |
| `TFTP_PORT` | `6969` | UDP port for TFTP transfer. |
| `BDP_VALUE` | `136` | `OMCI_CUSTOM_BDP` value. 136 = v0.1.0 behavior. 138 adds kernel P-bit module. |
| `EXTRA_FLASH_COMMANDS` | *(empty)* | Additional `flash set` commands injected into boot script. Chain with `&&`. |
| `TPCONF_COMMIT` | *(pinned)* | Git commit of `sta-c0000/tpconf_bin_xml` used for config encryption. |

### Extra flash commands

Set `EXTRA_FLASH_COMMANDS` before running the build to inject additional
`flash set` lines into the boot script. Use `&&` as separator (semicolons
are rejected by the firmware). Examples:

```shell
# Huawei OLT mode (from RTL960x community)
$ EXTRA_FLASH_COMMANDS=flash set OMCI_OLT_MODE 1 && flash set OMCI_FAKE_OK 1

# Full ONU identity clone
$ EXTRA_FLASH_COMMANDS=flash set PON_VENDOR_ID HWTC && flash set GPON_ONU_MODEL HG8240H && flash set HW_HWVER BF9.A && flash set OMCI_SW_VER1 V3R017C10S100 && flash set OMCI_SW_VER2 V3R017C10S100
```

Community-tested values: [Anime4000/RTL960x](https://github.com/Anime4000/RTL960x).

## How It Works

### Why direct MTD write?

The web UI firmware upgrade path verifies an RSA signature covering everything
past offset 0x200 in the firmware file. We do not have TP-Link's private key
and cannot create a valid signature.

U-Boot does not verify the SquashFS root filesystem partition (`/dev/mtd5`,
the `r0` partition). It only checks the kernel uImage CRC. The Linux kernel
mounts whatever SquashFS it finds on the partition with no cryptographic
verification. Writing a patched SquashFS directly to `/dev/mtd5` bypasses all
signature checks.

### Why the fix persists

The boot script `/etc/scripts/config_xmlconfig.sh` runs `flash set` on every
boot, writing the value to persistent MIB flash storage. By changing this from
`flash set OMCI_CUSTOM_BDP 2` to `flash set OMCI_CUSTOM_BDP 136`, the correct
value is re-applied on every boot regardless of what the OLT or any other
process might change.

### The `sys` command

The telnet CLI has a hidden `sys` command available only during the first
10 minutes after boot. Its arguments must be base64-encoded DES-encrypted
strings. The encryption key is derived from the device's `X_TP_ProductID`
XORed with a hardcoded base key in the CLI binary.

The `sys` subcommand `linuxsh` executes arbitrary shell commands via
`system()`. This gives full shell access within the time window — sufficient
to flash the rootfs.

Multi-command sequences must use `&&` as separator. Semicolons (`;`) are
detected and rejected by the firmware's `util_execSystem` function.

The first `sys` command after boot always fails silently because the CLI uses
the raw base key for the first command and the ProductID-derived key for
subsequent commands. The `warmup` command (`sys nF0fadtl3r4=`) exists solely
to consume this first-command state — it is encrypted with the derived key
and fails decryption with the base key, but the act of processing it advances
the state so all subsequent commands work normally.

## Safety

The device runs from an **in-memory copy** of the root filesystem. Erasing and
rewriting `/dev/mtd5` does not affect the running system. If the `verify` step
shows any corruption, re-erase and re-write as many times as needed. Only the
`reboot` command commits the change.

If the device does not boot after flashing, recovery without serial/UART access
is difficult. The `verify` step using `cmp` exists specifically to prevent a
bad flash from ever reaching reboot.

## Credits

- [Anime4000/RTL960x](https://github.com/Anime4000/RTL960x) — the definitive
  community resource for hacking Realtek RTL960x-based ONUs. Documents flash
  layouts, MIB parameters, OMCI diagnostics, and ISP-specific configurations.
- [sta-c0000/tpconf_bin_xml](https://github.com/sta-c0000/tpconf_bin_xml) —
  tool for decrypting and re-encrypting TP-Link config backup files.

## License

MIT

