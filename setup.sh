#!/usr/bin/env bash
set -e
export MSYS_NO_PATHCONV=1
USERS="admin openhab door window1 window2 motion smoke keypad siren lock light"

if [ ! -f .env ]; then
  : > .env
  for u in $USERS; do
    echo "MQTT_PASS_$(echo $u | tr a-z A-Z)=$(openssl rand -hex 12)" >> .env
  done
  echo "KEYPAD_PIN=$(shuf -i 1000-9999 -n 1)" >> .env
  echo ".env створено"
fi

rm -f mosquitto/config/passwd
first=1
for u in $USERS; do
  key="MQTT_PASS_$(echo $u | tr a-z A-Z)"
  pass=$(grep "^$key=" .env | cut -d= -f2)
  flag="-b"; [ $first = 1 ] && flag="-c -b"; first=0
  docker run --rm -v "$(pwd)/mosquitto/config:/mosquitto/config" \
    eclipse-mosquitto:2 mosquitto_passwd $flag /mosquitto/config/passwd "$u" "$pass"
done
echo "passwd створено"