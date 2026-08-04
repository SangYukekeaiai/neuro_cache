$ErrorActionPreference = "Stop"

$distro = "Ubuntu"
$taskName = "Sync Neuro-cache research survey"
$wslUser = (& wsl.exe -d $distro -- bash -lc 'printf %s "$USER"').Trim()
if (-not $wslUser) {
    throw "Could not determine the Ubuntu user."
}

& wsl.exe -d $distro -- bash -lc 'command -v rsync >/dev/null && command -v flock >/dev/null && command -v ssh >/dev/null'
if ($LASTEXITCODE -ne 0) {
    throw "Ubuntu needs rsync, flock, and ssh. Run: wsl -d Ubuntu -- sudo apt update && sudo apt install -y rsync openssh-client util-linux"
}

$sshDir = "/home/$wslUser/.ssh"
$sshConfigPath = "$sshDir/neuro-cache-sync.conf"
$binDir = "/home/$wslUser/.local/bin"
$syncPath = "$binDir/sync-neuro-cache-survey"
$connectPath = "$binDir/connect-delta-sync"

$sshConfig = @'
Host delta-neuro-cache
    HostName login.delta.ncsa.illinois.edu
    User yyu9
    ControlMaster auto
    ControlPersist no
    ControlPath ~/.ssh/neuro-cache-sync-%C
    ServerAliveInterval 60
    ServerAliveCountMax 3
'@

$syncScript = @'
#!/usr/bin/env bash
set -u

source_path="delta-neuro-cache:/u/yyu9/projects/neuro_cache/research_survey/"
destination="/mnt/e/research_lib/project_related/Neuro-cache/"
ssh_config="$HOME/.ssh/neuro-cache-sync.conf"
state_dir="$HOME/.local/state"
log_path="$state_dir/neuro-cache-survey-sync.log"
lock_path="$state_dir/neuro-cache-survey-sync.lock"

mkdir -p "$destination" "$state_dir"
exec 9>"$lock_path"
flock -n 9 || exit 0

output=$(rsync \
    --recursive \
    --times \
    --omit-dir-times \
    --compress \
    --partial \
    --delay-updates \
    --update \
    --itemize-changes \
    -e "ssh -F $ssh_config -o PermitLocalCommand=no -o BatchMode=yes -o ConnectTimeout=15" \
    "$source_path" \
    "$destination" 2>&1)
status=$?

if [[ $status -ne 0 || -n $output ]]; then
    {
        printf '[%s] exit=%d\n' "$(date --iso-8601=seconds)" "$status"
        printf '%s\n' "$output"
    } >>"$log_path"
fi

exit "$status"
'@

$connectScript = @'
#!/usr/bin/env bash
set -u

ssh_config="$HOME/.ssh/neuro-cache-sync.conf"
sync_script="$HOME/.local/bin/sync-neuro-cache-survey"
host="delta-neuro-cache"
sync_pid=""

cleanup() {
    trap - EXIT INT TERM
    if [[ -n $sync_pid ]]; then
        kill "$sync_pid" 2>/dev/null || true
        wait "$sync_pid" 2>/dev/null || true
    fi
    ssh -F "$ssh_config" -O exit "$host" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if ! ssh -F "$ssh_config" -MNf "$host"; then
    exit 1
fi

"$sync_script" || true
(
    while sleep 300; do
        "$sync_script" || true
    done
) &
sync_pid=$!

ssh -F "$ssh_config" "$host"
exit $?
'@

function Install-WslFile {
    param(
        [string]$Directory,
        [string]$Path,
        [string]$Content,
        [string]$Mode
    )

    $unixContent = $Content.Replace("`r`n", "`n")
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($unixContent))
    $command = "install -d -m 700 '$Directory' && printf '%s' '$encoded' | base64 --decode > '$Path' && chmod $Mode '$Path'"
    & wsl.exe -d $distro -- bash -lc $command
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install $Path in Ubuntu."
    }
}

Install-WslFile -Directory $sshDir -Path $sshConfigPath -Content $sshConfig -Mode "600"
Install-WslFile -Directory $binDir -Path $syncPath -Content $syncScript -Mode "700"
Install-WslFile -Directory $binDir -Path $connectPath -Content $connectScript -Mode "700"

$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$launcherPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Connect Delta and Sync.cmd"
$launcher = @'
@echo off
wsl.exe -d Ubuntu -- bash -lc "exec ~/.local/bin/connect-delta-sync"
'@
[IO.File]::WriteAllText($launcherPath, $launcher.Replace("`r`n", "`n"), [Text.Encoding]::ASCII)

Write-Host "Authenticate to Delta once with your password and Duo:"
& wsl.exe -d $distro -- bash -lc "ssh -F '$sshConfigPath' -MNf delta-neuro-cache"
if ($LASTEXITCODE -ne 0) {
    throw "Delta authentication failed."
}

try {
    & wsl.exe -d $distro --exec $syncPath
    if ($LASTEXITCODE -ne 0) {
        throw "The initial sync failed. Check the WSL log at ~/.local/state/neuro-cache-survey-sync.log."
    }
} finally {
    & wsl.exe -d $distro -- bash -lc "ssh -F '$sshConfigPath' -O exit delta-neuro-cache >/dev/null 2>&1 || true"
}

Write-Host "Sync installed and the initial transfer completed."
Write-Host "Destination: E:\research_lib\project_related\Neuro-cache"
Write-Host "Launcher: $launcherPath"
Write-Host "The sync runs on connection and every five minutes while the launcher shell is open."
Write-Host "Closing the Delta shell stops the sync loop and SSH master connection."
