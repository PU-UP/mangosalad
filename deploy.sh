#!/bin/sh
set -eu
cd /home/ubuntu/mangosalad-desk
backup="/home/ubuntu/mangosalad-desk/backups/pre-desk-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
chmod 700 /home/ubuntu/mangosalad-desk/backups "$backup"
sudo -n tar -czf "$backup/old-website.tar.gz" -C /var/www mangosalad
sudo -n cp -L /etc/nginx/sites-enabled/mangosalad.conf "$backup/nginx.conf"
sudo -n chown -R ubuntu:ubuntu "$backup"
chmod 600 "$backup"/*
sudo -n cp nginx.conf /etc/nginx/sites-available/mangosalad-desk.conf
sudo -n ln -sfn /etc/nginx/sites-available/mangosalad-desk.conf /etc/nginx/sites-enabled/mangosalad.conf
if ! sudo -n nginx -t; then
  sudo -n cp "$backup/nginx.conf" /etc/nginx/sites-available/mangosalad-desk.conf
  exit 1
fi
sudo -n systemctl reload nginx
printf '%s\n' "$backup" > last-backup.txt
echo 'New website routed; previous website backed up.'
curl -fsS --resolve mangosalad.cn:443:127.0.0.1 https://mangosalad.cn/health
