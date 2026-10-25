@echo off
rem Removes all collector tasks.
for %%T in (snapshot_0030 snapshot_0630 snapshot_1230 snapshot_1830 day_0115) do schtasks /Delete /F /TN "CAMMESA\%%T"
