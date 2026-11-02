# -*- coding: utf-8 -*-
"""邮件服务：从 local_store.py 迁移出来的 SMTP 发送能力（配置路径不变）。"""

import json
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr


def config_path(platform_root: str) -> str:
    return os.path.join(os.path.dirname(platform_root), "localdata", "mail_config.json")


DEFAULTS = {
    "enabled": False,
    "smtp_host": "smtp.163.com", "smtp_port": 465, "use_ssl": True,
    "user": "", "password": "",
    "from_addr": "",
    "to_addrs": [], "cc_addrs": [], "puppy_addr": "",
}


def load_mail_config(platform_root: str) -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(config_path(platform_root), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def send_mail(platform_root: str, subject: str, body: str, to_addrs=None):
    cfg = load_mail_config(platform_root)
    if not cfg.get("enabled") or not cfg.get("password"):
        return False, "邮件提醒未启用（mail_config.json 未配置 enabled/password）"
    try:
        if to_addrs:
            recipients = list(to_addrs)
        else:
            recipients = list(cfg.get("to_addrs") or [])
            for cc in (cfg.get("cc_addrs") or []):
                if cc not in recipients:
                    recipients.append(cc)
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = formataddr(("KittenPuppy4Ever 许愿池", cfg.get("from_addr") or ""))
        msg["To"] = ", ".join(cfg.get("to_addrs") or [])
        if not to_addrs and cfg.get("cc_addrs"):
            msg["Cc"] = ", ".join(cfg["cc_addrs"])
        if cfg.get("use_ssl"):
            srv = smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], timeout=20,
                                   context=ssl.create_default_context())
        else:
            srv = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=20)
        srv.ehlo()
        if not cfg.get("use_ssl") and srv.has_extn("starttls"):
            srv.starttls(context=ssl.create_default_context())
            srv.ehlo()
        if srv.has_extn("auth"):
            srv.login(cfg["user"], cfg["password"])
        srv.sendmail(cfg["from_addr"], recipients, msg.as_string())
        srv.quit()
        return True, "已发送"
    except Exception as e:
        return False, "发送失败：" + str(e)


def mail_status(platform_root: str) -> dict:
    cfg = load_mail_config(platform_root)
    return {
        "enabled": bool(cfg.get("enabled") and cfg.get("password")),
        "host": cfg.get("smtp_host"), "port": cfg.get("smtp_port"),
        "from": cfg.get("from_addr"),
        "to_addrs": cfg.get("to_addrs", []),
        "cc_addrs": cfg.get("cc_addrs", []),
    }
