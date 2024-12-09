# DBI backend

PC-side server for games installation into Nintendo Switch

## Requirements
Host:

- libusb
- pyusb
- python3.7+

Nintendo Switch:
- DBI v202+

## Usage

1. Git clone this repository `git clone git@github.com:lunixoid/dbibackend.git`
1. `cd dbibackend`
1. Run `sudo bash` to start a bash shell in case you are using zsh or fish.
   You need root privileges to access the USB device.
1. Run `. ./env.sh` to set up the environment.
   This will set up the python environment and its dependencies.
1. Run `dbi -d <PATH_TO_ROM_DIRERCTORY>` 
