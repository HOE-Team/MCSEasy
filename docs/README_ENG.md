# Minecraft Simple Server Launcher — MCSEasy

<p align="center">
  <img src="../logo.svg" alt="MCSEasy Logo" width="150">
</p>

<div align="center">
<p align="center">
  <b><a href=../README.md>简体中文</a> | <a href=README_ZHTW.md_>繁體中文</a> | <a>English</a></b>
  </p>

[![Stars](https://img.shields.io/github/stars/GoldenHoe/MCSEasy?style=for-the-badge&logo=data:image/svg%2bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZlcnNpb249IjEiIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiI+PHBhdGggZD0iTTggLjI1YS43NS43NSAwIDAgMSAuNjczLjQxOGwxLjg4MiAzLjgxNSA0LjIxLjYxMmEuNzUuNzUgMCAwIDEgLjQxNiAxLjI3OWwtMy4wNDYgMi45Ny43MTkgNC4xOTJhLjc1MS43NTEgMCAwIDEtMS4wODguNzkxTDggMTIuMzQ3bC0zLjc2NiAxLjk4YS43NS43NSAwIDAgMS0xLjA4OC0uNzlsLjcyLTQuMTk0TC44MTggNi4zNzRhLjc1Ljc1IDAgMCAxIC40MTYtMS4yOGw0LjIxLS42MTFMNy4zMjcuNjY4QS43NS43NSAwIDAgMSA4IC4yNVoiIGZpbGw9IiNlYWM1NGYiLz48L3N2Zz4=&logoSize=auto&label=Stars&labelColor=444444&color=eac54f)](https://github.com/GoldenHoe/MCSEasy)
[![LICENSE](https://img.shields.io/github/license/GoldenHoe/MCSEasy?style=for-the-badge)](https://github.com/GoldenHoe/MCSEasy/blob/main/LICENSE)
![GitHub Release](https://img.shields.io/github/v/release/GoldenHoe/MCSEasy?label=Release&logo=github&style=for-the-badge)
</div>

### For *helping users who want to create a Minecraft server to start and monitor their MC server*

## Overview

This project is a **tool for automating the deployment of Minecraft servers**, written in **Python** and packaged with **PyInstaller**.
It is intended to **simplify server installation and startup**, making it easier for users to deploy and monitor their Minecraft servers.

## Why choose MCSEasy?

### ✨ Lightweight
Small footprint — no need to install third-party applications; run with a single click.
<div align="center">
    <img src="../images/MXIntro.png" style="border-radius: 5px;" alt="MXIntro">
</div>

### ⭐ Fast Management
A clear UI makes server management quick and convenient.
<div align="center">
    <img src="../images/UIIntro.png" width="75%" style="border-radius: 5px;" alt="UIIntro">
</div>

### 🛠️ Version Support
MCSEasy supports downloading multiple server types. Forge downloads use high-speed sources provided by [BMCLAPI ↗](https://bmclapidoc.bangbang93.com/).
<div align="center">
    <img src="../images/VSIntro.png" width="75%" style="border-radius: 5px;" alt="VSIntro">
</div>

> **Note**
> #### Server types supported for download in MCSEasy 1.2
> - Vanilla
> - Paper
> - Forge
> - Fabric

### 🎨 Customization
Provides basic personalization options and an optional semi-transparent window mode.
<div align="center">
    <img src="./images/GXHIntro.png" width="75%" style="border-radius: 5px;" alt="VSIntro">
</div>

## Usage

### System requirements (mandatory)
1. A supported Windows version:
    > **Supported Windows versions:**
    > - Windows 7 with Service Pack 1/2 (Build 7601/7602)
    > - Windows Server 2008 R2 Service Pack 1/2 (Build 7601/7602)
    > - Windows 8 (Build 9200)
    > - Windows Server 2012 (Build 9200)
    > - Windows 8.1 (Build 9600)
    > - Windows Server 2012 R2 (Build 9600)
    > - Windows 10
    > - Windows Server 2016/2019/2022 (Build 14393/17763/20348)
    > - Windows 11
    > - Windows Server 2025 (Build 26100)

    > **Warning:**
    > Linux distributions are not supported at this time.
2. Network connection.

### Recommendations
1. Java Development Kit (JDK) 8 or OpenJDK 8.
2. Sufficient disk space for Minecraft server files.
3. CPU: recommended 2 cores or more (8 cores recommended for best performance).
4. At least 2 GB of RAM.
5. Use Ethernet with 100 Mbps or higher.
6. Use NAT traversal tools such as frp if needed (public IP not required).
7. Install Python 3.6 or newer.

## Download

1. Clone this repository from GitHub.
2. Download the packaged archive and extract it to a folder.
3. Download the release build (packaged as an .exe).

## Start

After extraction, **run directly**: `MCSEasy-vx.x.x.x-<release-type>.exe`

### Release type notes (applied since v1.2.0.0-Beta1)
- Beta (testing, unstable)
- RC (Release Candidate)
- GA (General Availability, stable release)
- LTS (Long Term Support — only one LTS release: `LTS Release-v1.0.0`; this release became unavailable after November 1, 2024)
- EP (Emergency Patch)

```
# Version examples
MCSEasy <version>-<release-type>

MCSEasy v1.2.0.0-Beta1 (Beta)
MCSEasy v1.2.0.0-RC1 (Release Candidate)
MCSEasy v1.2.0.0-RC1-GUIRefactor (RC with descriptor suffix)
MCSEasy v1.2.0.0-GA (General Availability)
```

## Notes

Depending on your computer performance and network conditions, some operations (downloads and startup) may take some time.

## *AI Content Note

Some GUI code in this project was assisted by ChatGPT / Google Gemini and later reviewed and modified by humans.
AI-generated content is used to speed development and is not guaranteed to be perfect. Project maintenance and responsibility remain with the developers.

## Contributing & Feedback

If you find issues or have suggestions, please email **hoe_team@outlook.com**. Contributions of code, documentation, and testing are welcome.
Project app icon generated with [AppIcon Force ↗](https://zhangyu1818.github.io/appicon-forge/).

## License

Copyright © 2024–2025 HOE Team

This project is licensed under the [MIT License ↗](https://github.com/GoldenHoe/MCSEasy/blob/main/LICENSE).

> **Note** — This license means:
> 1. **You are free to use this code** for personal or commercial projects.
> 2. **You may modify and redistribute** the code.
> 3. **You may use it to develop and sell commercial software**, provided you include the original MIT license text and copyright notice.
> 4. **The author provides no warranty**; you use the software at your own risk.
