#!/usr/bin/env bash
set -e
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")"

openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 365 \
  -subj "/CN=IoT-Home-CA" -out ca.crt

openssl genrsa -out server.key 2048
openssl req -new -key server.key -subj "/CN=localhost" -out server.csr
printf "subjectAltName=DNS:localhost,DNS:mosquitto,IP:127.0.0.1" > san.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 365 -sha256 -extfile san.ext
rm -f server.csr san.ext
echo "Сертифікати згенеровано"