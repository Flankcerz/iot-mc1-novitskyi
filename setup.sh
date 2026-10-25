#!/usr/bin/env bash
set -e
export MSYS_NO_PATHCONV=1
USERS="admin openhab door window1 window2 motion smoke keypad siren lock light"

# --- .env з випадковими паролями (створюється лише якщо його немає) ---
if [ ! -f .env ]; then
  : > .env
  for u in $USERS; do
    echo "MQTT_PASS_$(echo $u | tr a-z A-Z)=$(openssl rand -hex 12)" >> .env
  done
  echo "KEYPAD_PIN=$(shuf -i 1000-9999 -n 1)" >> .env
  echo ".env створено"
fi

# --- файл паролів Mosquitto ---
rm -f mosquitto/config/passwd
first=1
for u in $USERS; do
  key="MQTT_PASS_$(echo $u | tr a-z A-Z)"
  pass=$(grep "^$key=" .env | cut -d= -f2)
  flag="-b"; [ $first = 1 ] && flag="-c -b"; first=0
  docker run --rm -v "$(pwd)/mosquitto/config:/mosquitto/config" \
    eclipse-mosquitto:2 mosquitto_passwd $flag /mosquitto/config/passwd "$u" "$pass"
done
docker run --rm -v "$(pwd)/mosquitto/config:/mosquitto/config" \
  eclipse-mosquitto:2 sh -c "chown mosquitto:mosquitto /mosquitto/config/passwd; chmod 0644 /mosquitto/config/passwd"
echo "passwd створено"

# --- truststore для openHAB: системні CA + наш CA, формат JKS ---
rm -f certs/truststore.jks
docker run --rm --entrypoint sh -v "$(pwd)/certs:/certs" openhab/openhab:latest -c '
  CACERTS="$(dirname "$(dirname "$(readlink -f "$(which keytool)")")")/lib/security/cacerts"
  keytool -importkeystore -noprompt \
    -srckeystore "$CACERTS" -srcstorepass changeit \
    -destkeystore /certs/truststore.jks -deststoretype JKS -deststorepass changeit &&
  keytool -importcert -noprompt -alias iot-ca -file /certs/ca.crt \
    -keystore /certs/truststore.jks -storetype JKS -storepass changeit'

# --- openHAB: mqtt.things з шаблону (пароль береться з .env) ---
mkdir -p openhab/conf/things
OH_PASS=$(grep '^MQTT_PASS_OPENHAB=' .env | cut -d= -f2)
sed "s/__OPENHAB_PASS__/$OH_PASS/" openhab/templates/mqtt.things.template \
  > openhab/conf/things/mqtt.things
echo "openHAB: truststore і mqtt.things створено"