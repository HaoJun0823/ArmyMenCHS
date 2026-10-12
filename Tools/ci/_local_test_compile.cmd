@echo off
REM 本地验证 compile_dll_wine.py 所用的 cl/link 配方（Windows + VS2017 v141）
REM 与 CI 上 msvc-wine 的 wrapper 同源：Hostx64\x86 cl.exe（64位宿主编32位目标）
REM
REM ★ C1356 坑：Hostx64\x86\cl.exe 启动时按 PATH 找 mspdbcore.dll，
REM   该文件只在 Hostx64\x64 目录 —— 故 PATH 必须同时含两者。
REM   这与 MajestyIIExtend 的 CI 注释记录的坑完全一致。

set VC=C:\Program Files (x86)\Microsoft Visual Studio\2017\Professional\VC\Tools\MSVC\14.16.27023
set SDK=C:\Program Files (x86)\Windows Kits\10
set SDKVER=10.0.26100.0

set INCLUDE=%VC%\include;%SDK%\Include\%SDKVER%\ucrt;%SDK%\Include\%SDKVER%\um;%SDK%\Include\%SDKVER%\shared
set LIB=%VC%\lib\x86;%SDK%\Lib\%SDKVER%\ucrt\x86;%SDK%\Lib\%SDKVER%\um\x86
set PATH=%VC%\bin\Hostx64\x86;%VC%\bin\Hostx64\x64;%PATH%

cd /d "%~dp0..\..\Army1_Extend_Dll"
if exist Release rmdir /s /q Release
mkdir Release

echo === 1/4 预编译头 ===
cl /nologo /c /GS /W3 /Gy /Zc:wchar_t /Zc:inline /Zc:forScope /Gd /O2 /Oi /Oy- /fp:precise /MT /EHsc /utf-8 /Ycpch.h /D_WINDLL /D_UNICODE /DUNICODE /DNDEBUG /I. /FpRelease\Army1_Extend_Dll.pch /FoRelease\ pch.cpp
if errorlevel 1 goto fail

echo === 2/4 dllmain.cpp ===
cl /nologo /c /GS /W3 /Gy /Zc:wchar_t /Zc:inline /Zc:forScope /Gd /O2 /Oi /Oy- /fp:precise /MT /EHsc /utf-8 /Yupch.h /D_WINDLL /D_UNICODE /DUNICODE /DNDEBUG /I. /FpRelease\Army1_Extend_Dll.pch /FoRelease\dllmain.obj dllmain.cpp
if errorlevel 1 goto fail

echo === 3/4 hooks.cpp ===
cl /nologo /c /GS /W3 /Gy /Zc:wchar_t /Zc:inline /Zc:forScope /Gd /O2 /Oi /Oy- /fp:precise /MT /EHsc /utf-8 /Yupch.h /D_WINDLL /D_UNICODE /DUNICODE /DNDEBUG /I. /FpRelease\Army1_Extend_Dll.pch /FoRelease\src_hooks.obj src\hooks.cpp
if errorlevel 1 goto fail

echo === 4/4 ini_reader.cpp ===
cl /nologo /c /GS /W3 /Gy /Zc:wchar_t /Zc:inline /Zc:forScope /Gd /O2 /Oi /Oy- /fp:precise /MT /EHsc /utf-8 /Yupch.h /D_WINDLL /D_UNICODE /DUNICODE /DNDEBUG /I. /FpRelease\Army1_Extend_Dll.pch /FoRelease\src_ini_reader.obj src\ini_reader.cpp
if errorlevel 1 goto fail

echo === 链接 ===
link /nologo /DLL /MACHINE:X86 /OPT:REF /OPT:ICF /INCREMENTAL:NO /SUBSYSTEM:WINDOWS Release\pch.obj Release\dllmain.obj Release\src_hooks.obj Release\src_ini_reader.obj kernel32.lib user32.lib gdi32.lib advapi32.lib /OUT:Release\Army1_Extend_Dll.dll /IMPLIB:Release\Army1_Extend_Dll.lib
if errorlevel 1 goto fail

echo === 产物 ===
dir Release\Army1_Extend_Dll.dll
echo OK
exit /b 0

:fail
echo FAILED
exit /b 1
