@echo off
rem Creates the collector tasks in Windows Task Scheduler (current user, runs while logged on).
set "RUN=%~dp0run_collector.bat"
schtasks /Create /F /TN "CAMMESA\snapshot_0030" /SC DAILY /ST 00:30 /TR "\"%RUN%\" snapshot"
schtasks /Create /F /TN "CAMMESA\snapshot_0630" /SC DAILY /ST 06:30 /TR "\"%RUN%\" snapshot"
schtasks /Create /F /TN "CAMMESA\snapshot_1230" /SC DAILY /ST 12:30 /TR "\"%RUN%\" snapshot"
schtasks /Create /F /TN "CAMMESA\snapshot_1830" /SC DAILY /ST 18:30 /TR "\"%RUN%\" snapshot"
schtasks /Create /F /TN "CAMMESA\day_0115" /SC DAILY /ST 01:15 /TR "\"%RUN%\" day"
echo.
schtasks /Query /FO TABLE | findstr /I /C:"CAMMESA" /C:"TaskName"
