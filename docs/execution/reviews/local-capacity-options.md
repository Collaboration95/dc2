# Project-local scaling capacity: bounded feasibility review

Investigated 13 October 2026. **Credible minimal option: Lima 2.2.1, native
arm64 Linux, Apple VZ, rootful Docker, 8 vCPU / 8 GiB.** This is source/documentation
feasibility, not a successful boot or scaling result. The parent retains the
execution decision. No dependencies were installed, release assets downloaded,
VMs started, or settings changed; this review is the only file written.

## Evidence and choice

- Read-only host checks: macOS 26.6.2, arm64, 10 logical CPUs, 32 GiB RAM,
  approximately 187 GiB available disk. Existing Docker reports 2 CPUs and
  2,069,843,968 bytes RAM; Compose 2.33.1 is available. Neither `limactl` nor
  `colima` is on PATH. Authenticated `gh` release/source reads succeeded.
- [Lima VZ support](https://lima-vm.io/docs/config/vmtype/vz/) requires macOS
  13+ and native guest architecture. [Installation](https://lima-vm.io/docs/installation/)
  permits extracting release archives elsewhere; QEMU is required only for its
  own driver. This option needs no Homebrew install, QEMU, Rosetta, host sudo,
  vmnet helper, or global Docker context changes.
- `gh release view --repo lima-vm/lima` identified
  [v2.2.1](https://github.com/lima-vm/lima/releases/tag/v2.2.1), published
  3 October 2026, with `lima-2.2.1-Darwin-arm64.tar.gz` (38,328,082 bytes).
  Its published SHA-256 is
  `9e9eacce88f37e185c346bad73aa6136f738d8cdf8c3bb23cd42b071824bc66e`.
  The main archive includes the native guest agent; additional guest agents
  serve other architectures and are unnecessary here.
- Colima also supports VZ on macOS 13+, configurable CPU/memory and
  `autoActivate: false`: see its [pinned defaults](https://github.com/abiosoft/colima/blob/v0.10.3/embedded/defaults/colima.yaml).
  Authenticated release reads found [v0.10.3](https://github.com/abiosoft/colima/releases/tag/v0.10.3)
  and `colima-Darwin-arm64` (15,656,320 bytes). It adds an orchestration layer,
  and its default guest image comes from GitHub. Direct Lima already meets the
  need, so no second implementation or compatibility investigation is proposed.

Eight guest CPUs leave a nominal two CPUs beyond three workers' combined six
CPU quota. These are scheduled virtual CPUs, not dedicated physical cores.
Eight GiB is a starting allocation, subject to measured stack memory usage.
Apple CPU heterogeneity, other host workloads and thermal throttling remain
experimental confounders; this does not establish the proposal's speedup targets.

## Commands for the parent, not executed

Run in one disposable shell from the repository root. All created directories
below are already covered by `.local/` and `.cache/` ignore rules. Keep VM name
`d` short: the longest SSH socket path is 97 bytes here, below macOS's 104-byte
limit. Moving to a longer checkout path can invalidate this option.

```sh
cd /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2
DC2_ROOT="$PWD"
export LIMA_HOME="$DC2_ROOT/.local/lima"
export DOCKER_CONFIG="$DC2_ROOT/.local/docker"
export TMPDIR="$DC2_ROOT/.cache/tmp"
mkdir -p "$LIMA_HOME" "$DOCKER_CONFIG/cli-plugins" "$TMPDIR" \
  "$DC2_ROOT/.local/lima-dist" "$DC2_ROOT/.cache/capacity"

# GitHub transfers exclusively through authenticated gh; pin the reviewed asset.
gh release download v2.2.1 --repo lima-vm/lima \
  --pattern lima-2.2.1-Darwin-arm64.tar.gz --dir .cache/capacity
printf '%s  %s\n' \
  9e9eacce88f37e185c346bad73aa6136f738d8cdf8c3bb23cd42b071824bc66e \
  .cache/capacity/lima-2.2.1-Darwin-arm64.tar.gz | shasum -a 256 -c -
# Proceed only after the checksum passes; retain the complete archive layout.
tar -xzf .cache/capacity/lima-2.2.1-Darwin-arm64.tar.gz -C .local/lima-dist
DC2_LIMACTL="$DC2_ROOT/.local/lima-dist/bin/limactl"
codesign --verify --strict "$DC2_LIMACTL"
codesign -d --entitlements :- "$DC2_LIMACTL"

# Preserve access to existing CLI plugins without writing ~/.docker.
ln -s /Users/speedpowermac/.docker/cli-plugins/docker-compose \
  "$DOCKER_CONFIG/cli-plugins/docker-compose"
ln -s /Users/speedpowermac/.docker/cli-plugins/docker-buildx \
  "$DOCKER_CONFIG/cli-plugins/docker-buildx"

# Prefetch the pinned official Ubuntu image into the project, not Lima's cache.
curl --fail --location \
  https://cloud-images.ubuntu.com/releases/resolute/release-20260927/ubuntu-26.04-server-cloudimg-arm64.img \
  --output .cache/capacity/ubuntu-arm64.img
printf '%s  %s\n' \
  63a93bd5a8d76e33b15ceb5daa3657bd79be804748051ab178e643b0f5da22e7 \
  .cache/capacity/ubuntu-arm64.img | shasum -a 256 -c -

# EXECUTION DECISION: only after checks pass and the parent chooses to start.
"$DC2_LIMACTL" start --yes --name=d --vm-type=vz --arch=aarch64 \
  --cpus=8 --memory=8 --disk=40 --mount-type=virtiofs \
  --mount-only="$DC2_ROOT:w" \
  --set ".images = [{\"location\": \"$DC2_ROOT/.cache/capacity/ubuntu-arm64.img\", \"arch\": \"aarch64\", \"digest\": \"sha256:63a93bd5a8d76e33b15ceb5daa3657bd79be804748051ab178e643b0f5da22e7\"}]" \
  template:docker-rootful
unset DOCKER_CONTEXT DOCKER_TLS_VERIFY DOCKER_CERT_PATH
export DOCKER_HOST="unix://$LIMA_HOME/d/sock/docker.sock"
docker info --format '{{.NCPU}} {{.MemTotal}} {{.Architecture}} {{.CgroupVersion}}'
docker compose version
docker run --rm --cpus=2 alpine:3.22 cat /sys/fs/cgroup/cpu.max
# Expect a finite quota/period ratio of 2 (normally 200000 100000), not "max".
# After the chosen experiment and normal container shutdown:
"$DC2_LIMACTL" stop d
```

Use a project-local Compose override containing `cpus: 2.0` on the **actual
Processing worker service**, then scale that service to 1/2/3 replicas. Verify
each container's `HostConfig.NanoCpus == 2000000000` and its cgroup `cpu.max`
ratio is 2 before recording results. CPU shares and FFmpeg thread counts alone
are not hard caps. Do not run the inherited worker stack as acceptance evidence
for the new service boundary. A fresh daemon has separate images and volumes;
rebuild/bootstrap the selected project stack and avoid host port collisions with
the existing Docker Desktop stack.

## Isolation and blockers

- **Cache trap:** `LIMA_HOME` isolates VM state/keys/configuration, but Lima's
  [downloader](https://github.com/lima-vm/lima/blob/v2.2.1/pkg/downloader/downloader.go)
  uses Go's macOS user cache directory (`~/Library/Caches/lima`); XDG cache
  settings do not relocate that Darwin path. Local source files bypass caching.
  The command replaces all remote image entries with one verified local file.
  The [rootful template](https://github.com/lima-vm/lima/blob/v2.2.1/templates/docker-rootful.yaml)
  disables Lima-managed containerd, avoiding its GitHub nerdctl download. Native
  guest agents/templates come from the extracted archive. Do not substitute a
  remote image/template or change the user's `HOME`.
- The template installs Docker **inside the VM** through `get.docker.com` and
  configures its guest socket. Its displayed context commands are suggestions;
  do not execute them. `DOCKER_HOST` and the private `DOCKER_CONFIG` select the
  daemon and contain client/build caches without changing global contexts.
  Mounting only dc2 replaces the template's default home mount. Use default
  networking; do not enable vmnet, bridged networking, or privileged helpers.
- **Signing:** the release [build recipe](https://github.com/lima-vm/lima/blob/v2.2.1/Makefile)
  ad-hoc signs `limactl` with the
  [virtualization entitlement](https://github.com/lima-vm/lima/blob/v2.2.1/vz.entitlements).
  This requires no developer certificate or system trust change. The actual
  downloaded binary's signature/entitlements were not inspected in this review.
  Missing/invalid signing, Gatekeeper/quarantine, or managed-device policy can
  block execution. Stop and report such a block; no trust bypass is proposed.
- **User interaction:** `--yes` suppresses Lima's editor choice, not macOS
  privacy/security dialogs. Access to this Documents checkout or network access
  may require the user's response. No unattended first boot can be guaranteed.
- **Prerequisites:** built-in SSH tools, working DNS/HTTPS, the pinned Ubuntu
  URL, Ubuntu package repositories, Docker's installer/packages and container
  registry access are required. The dated image may eventually be removed;
  do not silently fall back to an unverified image. Sparse 40 GiB guest storage,
  builds and fixtures consume project disk. Existing CLI plugin symlinks must
  resolve; no new compiler/SDK is needed for the release-binary route.

Stop point reached: one credible project-local option with explicit first-run
and policy uncertainties. Boot, quota enforcement, memory headroom and measured
scaling remain for the parent's execution decision.
