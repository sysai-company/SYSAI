# SYSAI: установка агента на ПК сотрудника (docs/opo/TASKS.md, ОПО-6.2).
# Запуск — строка со страницы агента в SYSAI, в PowerShell (обычном, не от администратора):
#   $env:SYSAI_CODE='КОД'; irm __SYSAI_SERVER__/agents/api/install.ps1 | iex
# Ставит uv, синхронизатор SYSAI и Hermes (чего нет), создаёт профиль Hermes агента без встроенных навыков,
# применяет доступы, характер (SOUL.md) и навыки SYSAI_Hub, ставит окно агента «Агент SYSAI» (ярлык на рабочем
# столе), включает синхронизацию при входе в Windows.
# Повторный запуск с новым кодом обновляет то же самое. Совместим с Windows PowerShell 5.1.
& {
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

$Server = '__SYSAI_SERVER__'
$Wheel = '__SYSAI_WHEEL__'
$Version = '__SYSAI_VERSION__'
$SysaiHome = Join-Path $env:LOCALAPPDATA 'SYSAI'
# Переустановка на уже подключённом компьютере не требует нового кода: подключение (agent.json) остаётся своё.
$Joined = Test-Path (Join-Path $SysaiHome 'agent.json')

# Шаги нумеруются: окно установки показывает их списком с галочками, а не одной бегущей строкой.
$script:Step = 0
function Say([string]$Text) { $script:Step++; Write-Host ("SYSAI: [$($script:Step)] $Text") -ForegroundColor Cyan }
function Warn([string]$Text) { Write-Host "SYSAI: $Text" -ForegroundColor Yellow }
function Stop-Install([string]$Text) { Write-Host "SYSAI: $Text" -ForegroundColor Red; throw 'SYSAI-STOP' }
function Test-Command([string]$Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Update-PathNow {
    $parts = @([Environment]::GetEnvironmentVariable('Path', 'Machine'), [Environment]::GetEnvironmentVariable('Path', 'User'),
               (Join-Path $env:USERPROFILE '.local\bin'))
    $env:Path = ($parts | Where-Object { $_ }) -join ';'
}
function Stop-Sync {
    # the running synchronizer holds its files: asked to stop, then (if it did not) stopped by force
    $lock = Join-Path $SysaiHome 'run.lock'
    if (Test-Path $lock) {
        Set-Content -Path (Join-Path $SysaiHome 'stop') -Value 'stop' -ErrorAction SilentlyContinue
        for ($i = 0; ($i -lt 60) -and (Test-Path $lock); $i++) { Start-Sleep -Seconds 1 }
    }
    & taskkill /F /T /IM sysai-agentw.exe *> $null
    & taskkill /F /T /IM sysai-agent.exe *> $null
}

try {
    if ($env:OS -ne 'Windows_NT') { Stop-Install 'установщик — для Windows' }
    $Code = $env:SYSAI_CODE
    Remove-Item Env:SYSAI_CODE -ErrorAction SilentlyContinue
    if (-not $Code -and -not $Joined) { $Code = Read-Host 'Код подключения со страницы агента в SYSAI' }
    $Code = "$Code".Trim()
    if (-not $Code -and -not $Joined) { Stop-Install 'нет кода подключения: получите его на странице агента в SYSAI' }
    Say "сервер $Server, синхронизатор $Version"

    # 1. uv: ставит Python и синхронизатор, ничего не просит у администратора
    Update-PathNow
    if (-not (Test-Command 'uv')) {
        Say 'ставлю uv (Astral)...'
        & powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        Update-PathNow
        if (-not (Test-Command 'uv')) { Stop-Install 'uv не установился. Поставьте его по https://docs.astral.sh/uv/ и запустите установщик снова' }
    }

    # 2. синхронизатор SYSAI
    Say 'ставлю синхронизатор SYSAI...'
    Stop-Sync
    & uv tool install --force --python 3.12 $Wheel
    if ($LASTEXITCODE -ne 0) { Stop-Install 'синхронизатор не установился (uv tool install). Закройте Hermes, если он открыт, и запустите установщик снова' }
    & uv tool update-shell *> $null
    Update-PathNow
    if (-not (Test-Command 'sysai-agent')) { Stop-Install 'после установки не найдена команда sysai-agent: откройте новое окно PowerShell и запустите установщик снова' }

    # 3. код подключения → токен агента (хранилище Windows), ключ подписи доступов
    Say 'подключаю компьютер к SYSAI...'
    if ($Joined -and -not $Code) {
        Say 'компьютер уже подключён: оставляю прежнее подключение'
    } else {
        & sysai-agent connect --server $Server --code $Code
        if ($LASTEXITCODE -ne 0) {
            # Уже подключённый компьютер переустанавливают, чтобы обновить файлы: старое подключение не теряем.
            if ($Joined) { Warn 'код не принят: оставляю прежнее подключение компьютера' }
            else { Stop-Install 'код не принят. Получите новый на странице агента и запустите установщик снова' }
        }
    }
    $Info = (& sysai-agent status --json | Out-String) | ConvertFrom-Json
    $Agent = "$($Info.agent)"
    if (-not $Agent) { Stop-Install 'не удалось узнать имя агента (sysai-agent status)' }

    # 4. Hermes Agent
    if (-not (Test-Command 'hermes')) {
        Say 'ставлю Hermes Agent (Nous Research), это несколько минут...'

        # The Nous Research installer domain can return HTTP 403 for some networks.
        # Keep it as the primary source and fall back to the official GitHub repository.
        $sources = @(
            @{ Url = 'https://hermes-agent.nousresearch.com/install.ps1'; Name = 'Nous Research installer' },
            @{ Url = 'https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1'; Name = 'NousResearch/hermes-agent on GitHub' }
        )
        $text = $null
        foreach ($source in $sources) {
            try {
                Say "получаю установщик Hermes: $($source.Name)..."
                $response = Invoke-WebRequest -Uri $source.Url -UseBasicParsing -ErrorAction Stop
                $candidate = [string]$response.Content
                $candidate = $candidate.TrimStart([char]0xFEFF)

                # Do not execute an HTML block page or an unexpected response as PowerShell.
                if ($candidate -notmatch '(?m)^# Hermes Agent bootstrap:' -or
                    $candidate -notmatch '(?m)^param\(') {
                    throw 'источник вернул неожиданный документ, ожидается официальный install.ps1'
                }

                $text = $candidate
                Say "установщик Hermes получен: $($source.Name)"
                break
            }
            catch {
                $reason = "$($_.Exception.Message)"
                if ($reason.Length -gt 220) { $reason = $reason.Substring(0, 220) }
                Warn "источник $($source.Name) недоступен: $reason"
            }
        }

        if (-not $text) {
            Stop-Install 'не удалось загрузить официальный установщик Hermes ни с домена Nous Research, ни с GitHub. Проверьте подключение и повторите установку'
        }

        $tmp = Join-Path $env:TEMP 'sysai-hermes-install.ps1'
        try {
            [IO.File]::WriteAllText($tmp, $text, (New-Object Text.UTF8Encoding $true))
            & powershell -NoProfile -ExecutionPolicy Bypass -File $tmp -NonInteractive
        }
        finally {
            Remove-Item $tmp -ErrorAction SilentlyContinue
        }

        Update-PathNow
        if (-not (Test-Command 'hermes')) {
            Stop-Install 'Hermes не установился. Проверьте сообщения установщика выше и повторите запуск SYSAI installer'
        }
    }

    # 5. профиль Hermes агента — без встроенных навыков (нужные придут из SYSAI_Hub)
    & hermes profile show $Agent *> $null
    if ($LASTEXITCODE -ne 0) {
        Say "создаю профиль Hermes $Agent..."
        & hermes profile create $Agent --no-skills
        if ($LASTEXITCODE -ne 0) { Stop-Install "профиль Hermes $Agent не создался, см. сообщения выше" }
    }
    $ProfileDir = ''
    $show = (& hermes profile show $Agent 2> $null | Out-String)
    if ($show -match 'Path:\s*(\S[^\r\n]*)') { $ProfileDir = $Matches[1].Trim() }

    # 6. первая синхронизация: доступы, характер, навыки
    Say 'применяю доступы, характер и навыки из SYSAI...'
    if ($ProfileDir) { & sysai-agent sync --hermes-home $ProfileDir } else { & sysai-agent sync }
    if ($LASTEXITCODE -ne 0) { Warn 'синхронизация прошла с ошибками (см. выше): синхронизатор повторит сам' }

    # 7. окно агента «Агент SYSAI»: Electron и приложение, проверенные по подписи SYSAI, ярлыки на рабочем столе и в «Пуске»
    Say 'ставлю окно агента «Агент SYSAI» (в первый раз скачивается около 160 МБ)...'
    & sysai-agent desktop --install-only
    $DesktopOK = ($LASTEXITCODE -eq 0)
    if (-not $DesktopOK) { Warn 'окно агента не установилось (см. выше): синхронизатор попробует сам, или выполните sysai-agent desktop' }

    # 8. синхронизация в фоне: при входе в Windows и каждые 5 минут
    $runner = Get-Command 'sysai-agentw' -ErrorAction SilentlyContinue
    if (-not $runner) { $runner = Get-Command 'sysai-agent' }
    $exe = $runner.Source
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    New-ItemProperty -Path $runKey -Name 'SYSAI Agent' -Value ('"' + $exe + '" run') -PropertyType String -Force | Out-Null
    Start-Process -FilePath $exe -ArgumentList 'run' -WindowStyle Hidden
    Say 'синхронизация включена: при входе в Windows и каждые 5 минут'

    Write-Host ''
    Say "готово: агент $Agent на этом компьютере."
    if ($DesktopOK) { Write-Host '  Окно агента:           ярлык «Агент SYSAI» на рабочем столе (или sysai-agent desktop)' }
    else { Warn 'окно и ярлык ещё не установлены; проверьте сообщения выше и запустите sysai-agent desktop' }
    Write-Host "  Агент в терминале:     hermes -p $Agent"
    $Now = (& sysai-agent status --json | Out-String) | ConvertFrom-Json
    if ($Now.version) { Write-Host "  Синхронизатор:         $($Now.version)" }
    Write-Host '  Что на компьютере:     sysai-agent status'
    Write-Host "  Доступы, расходы, трасса - на странице агента в SYSAI: $Server/agents"
}
catch {
    if ("$_" -ne 'SYSAI-STOP') { Write-Host "SYSAI: установка прервалась: $_" -ForegroundColor Red }
}
}
