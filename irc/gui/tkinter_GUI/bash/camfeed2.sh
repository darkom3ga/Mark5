#!/bin/bash

ssh_login() {
    xdotool type "ssh kratos@192.168.1.10"
    xdotool key Return
    sleep 2  # Increase the delay to allow the command to execute
    xdotool type "kratos123"
    xdotool key Return
    sleep 2  # Increase the delay to allow the command to execute
    xdotool type "clear"
    xdotool key Return
    sleep 2  # Increase the delay to allow the command to execute
}

simulate_input() {
    xdotool type "$1"
    xdotool key Return
    sleep 2  # Increase the delay to allow the command to execute
}

split_vertical() {
    xdotool key Ctrl+Shift+E
    sleep 2  # Increase the delay to allow the command to execute
}

split_horizontal() {
    xdotool key Ctrl+Shift+O
    sleep 2  # Increase the delay to allow the command to execute
}

terminator_width=$(xdpyinfo | awk '/dimensions:/ {print $2}' | cut -d'x' -f1)
terminator_height=$(expr $(xdpyinfo | awk '/dimensions:/ {print $2}' | cut -d'x' -f2) / 2)

terminator --geometry=${terminator_width}x${terminator_height}+0+0 &
sleep 2  # Increase the delay to allow Terminator to start

# First window

ssh_login
simulate_input "rosrun irc2024 videofeed2 1"
xdotool key Ctrl+z 
simulate_input "bg"

simulate_input "disown -h"
simulate_input "exit"
simulate_input "exit"

