@echo off
REM ============================================================================
REM ArmyMenCHS —— update\ 分组开关工具
REM ----------------------------------------------------------------------------
REM 用途：update\ 里的资产分 6 组。逐个启用可定位是哪一组导致异常。
REM       原理：把不需要的组临时改名（加 _OFF 后缀），UAL 就看不到它们，
REM             游戏自动回落到根目录的原版文件。
REM
REM 用法：
REM   toggle_update.bat status        查看各组当前状态
REM   toggle_update.bat only Audio    只启用 Audio（其余全关）
REM   toggle_update.bat only Screens  只启用 Screens
REM   toggle_update.bat only Maps     只启用 Maps
REM   toggle_update.bat only AVI      只启用 AVI
REM   toggle_update.bat only Campaigns 只启用 Campaigns
REM   toggle_update.bat only objects   只启用三地形 objects.dat
REM   toggle_update.bat all           全部启用
REM   toggle_update.bat none          全部关闭
REM ============================================================================

setlocal enabledelayedexpansion
set GAME=I:\LocalGames\Army Men\Army Men I STEAM
set UPD=%GAME%\update

if "%~1"=="" goto usage
if /i "%~1"=="status" goto status
if /i "%~1"=="all"    goto all
if /i "%~1"=="none"   goto none
if /i "%~1"=="only"   goto only
goto usage

:status
echo === update\ 分组状态 ===
for %%G in (Audio AVI Campaigns Maps Screens Alpine Bayou Desert) do (
  if exist "%UPD%\%%G" (
    echo   [ON ] %%G
  ) else if exist "%UPD%\%%G_OFF" (
    echo   [OFF] %%G
  ) else (
    echo   [ -- ] %%G  ^(不存在^)
  )
)
goto end

:all
for %%G in (Audio AVI Campaigns Maps Screens Alpine Bayou Desert) do (
  if exist "%UPD%\%%G_OFF" ren "%UPD%\%%G_OFF" "%%G"
)
echo 已启用全部组。
goto status

:none
for %%G in (Audio AVI Campaigns Maps Screens Alpine Bayou Desert) do (
  if exist "%UPD%\%%G" ren "%UPD%\%%G" "%%G_OFF"
)
echo 已关闭全部组（游戏将使用根目录原版文件）。
goto status

:only
set WANT=%~2
if "%WANT%"=="" goto usage
for %%G in (Audio AVI Campaigns Maps Screens Alpine Bayou Desert) do (
  if /i "%%G"=="%WANT%" (
    if exist "%UPD%\%%G_OFF" ren "%UPD%\%%G_OFF" "%%G"
  ) else (
    if exist "%UPD%\%%G" ren "%UPD%\%%G" "%%G_OFF"
  )
)
echo 只启用 %WANT%。
goto status

:usage
echo 用法:
echo   toggle_update.bat status          查看状态
echo   toggle_update.bat only ^<组名^>    只启用某组
echo   toggle_update.bat all             全部启用
echo   toggle_update.bat none            全部关闭
echo.
echo 组名: Audio AVI Campaigns Maps Screens Alpine Bayou Desert
goto end

:end
endlocal
