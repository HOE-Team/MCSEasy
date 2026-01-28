<h1 align="center">Minecraft简易开服程序MCSEasy</h1>

<p align="center">
  <img src="logo.svg" alt="MCSEasy Logo" width="150">
</p>

> [!IMPORTANT]
> 因为出现了一些技术问题，MCSEasy仓库将被暂时归档，恢复时间待定，详见[HOE Team 理事会关于 HOE Team 暂停维护 MCSEasy 项目的技术说明](https://github.com/HOE-Team/Public_Document/blob/main/HOE%20Team%E7%90%86%E4%BA%8B%E4%BC%9A%E5%85%B3%E4%BA%8EHOE%20Team%E6%9A%82%E5%81%9C%E7%BB%B4%E6%8A%A4MCSEasy%E9%A1%B9%E7%9B%AE%E7%9A%84%E6%8A%80%E6%9C%AF%E8%AF%B4%E6%98%8E.pdf)

<div align="center">
<p align="center">
  <b><a>简体中文</a> | <a href="./docs/README_ZHTW.md">繁體中文</a> | <a href="./docs/README_ENG.md">English</a></b>
</p>

[![Stars](https://img.shields.io/github/stars/GoldenHoe/MCSEasy?style=for-the-badge&logo=data:image/svg%2bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZlcnNpb249IjEiIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiI+PHBhdGggZD0iTTggLjI1YS43NS43NSAwIDAgMSAuNjczLjQxOGwxLjg4MiAzLjgxNSA0LjIxLjYxMmEuNzUuNzUgMCAwIDEgLjQxNiAxLjI3OWwtMy4wNDYgMi45Ny43MTkgNC4xOTJhLjc1MS43NTEgMCAwIDEtMS4wODguNzkxTDggMTIuMzQ3bC0zLjc2NiAxLjk4YS43NS43NSAwIDAgMS0xLjA4OC0uNzlsLjcyLTQuMTk0TC44MTggNi4zNzRhLjc1Ljc1IDAgMCAxIC40MTYtMS4yOGw0LjIxLS42MTFMNy4zMjcuNjY4QS43NS43NSAwIDAgMSA4IC4yNVoiIGZpbGw9IiNlYWM1NGYiLz48L3N2Zz4=&logoSize=auto&label=Stars&labelColor=444444&color=eac54f)](https://github.com/GoldenHoe/MCSEasy)
[![LICENSE](https://img.shields.io/github/license/GoldenHoe/MCSEasy?style=for-the-badge)](https://github.com/GoldenHoe/MCSEasy/blob/main/LICENSE)
![GitHub Release](https://img.shields.io/github/v/release/GoldenHoe/MCSEasy?label=Release&logo=github&style=for-the-badge)
</div>

### 用于 *帮助有需要创建 Minecraft 服务器的用户开启并监视他们的MC服务器*


## 概述

本程序是一个**用于自动化部署 Minecraft 服务器的工具**，使用 **Python** 编写，**PyInstaller** 封装。
<br>它旨在**简化服务器的安装和启动操作，让有需要创建 Minecraft 服务器的用户能够更轻松地部署他们的 Minecraft 服务器并监视服务器状态**。

## MCSEasy有什么优点？

### ✨ 轻量化
占用小，无需安装第三方应用，点击即用。  
<div align="center">
    <img src="./images/MXIntro.png" style="border-radius: 5px;" alt="MXIntro">
</div>


### ⭐ 快捷管理
UI界面一目了然，服务器管理方便快捷  
<div align="center">
    <img src="./images/UIintro.png" width="75%" style="border-radius: 5px;" alt="UIIntro">
</div>

### 🛠️ 版本支持
MCSEasy拥有多个服务端的下载支持，Forge端使用 [BMCLAPI[↗]](https://bmclapidoc.bangbang93.com/) 提供的高速下载支持。
<div align="center">
    <img src="./images/VSIntro.png" width="75%" style="border-radius: 5px;" alt="VSIntro">
</div>

> [!NOTE]
> #### MCSEasy 1.2支持下载的服务端  
> - Vanilla  
> - Paper  
> - Forge  
> - Fabric  


### 🎨 个性化
提供基础的个性化以及可选的半透明窗口选项。
<div align="center">
    <img src="./images/GXHIntro.png" width="75%" style="border-radius: 5px;" alt="VSIntro">
</div>

## 使用指南
### 程序硬性要求
    
1. 计算机运行受支持的Windows/macOS/Linux版本  
在此查看[支持的系统版本[↗]](./docs/SUPPORTING_OS.md)

> [!WARNING]  
> 对Linux/macOS平台的构建有严重错误，暂时不建议使用。  
2. 网络连接。

### 建议拥有的软硬件环境
1. Java Development Kit(Java JDK) 8或OpenJDK 8。
2. 足够的磁盘空间用于Minecraft服务器文件。
3. CPU推荐2核心（物理核）及以上，8核心以上最佳。
4. 拥有至少2GB RAM（物理内存，非虚拟内存或SWAP分区）。
5. 使用100Mbps和以上的以太网连接
> [!NOTE]建议使用VPN以更快速的获取服务器版本列表和下载服务器。
6. 使用frp等内网穿透软件（公网IP可忽略）。
7. 下载Python3.6以上版本。

## 下载方式
1. 直接从GitHub仓库克隆本项目。
2. 下载发布的压缩包并解压到指定目录。
3. 下载Release的发布版本(已打包成exe可执行文件)

## 启动

解压后**直接**运行 `MCSEasy-vx.x.x.x-<发行类型>.exe`
### 发行版本号说明（v1.2.0.0-Beta1以后开始施行）
- Beta(测试版，不稳定)
- RC(Release Candidate，发布候选版)
- GA(General Availability，正式版)
- LTS(延长支持版本，只有一个发行的LTS版本：`LTS Release-v1.0.0`，此版本已在2024年11月1日后不可用)
- EP(Emergency Patch，紧急修复版本)
- 
```
# 版本号示例
MCSEasy <版本号>-<发行类型>

MCSEasy v1.2.0.0-Beta1 (测试版)
MCSEasy v1.2.0.0-RC1 (发布候选)
MCSEasy v1.2.0.0-RC1-GUIRefactor (带有说明后缀的发布候选)
MCSEasy v1.2.0.0-GA (正式版)
```

## 注意事项

根据你的计算机性能和网络状况，某些操作（下载与启动）可能需要一些时间。

## * AI 内容生成提示

本项目部分 GUI 代码由 ChatGPT / Google Gemini 辅助生成，后续已由人工审查和修改。  
AI 生成的内容仅用于提高开发效率，不保证完全正确性。项目维护与责任由开发者承担。  


## 贡献与反馈

如果你发现任何问题或有改进建议，请发送邮件到**hoe_team@outlook.com**。也欢迎任何形式的贡献，包括代码、文档和测试。  
本项目应用图标生成自[AppIcon Force[↗]](https://zhangyu1818.github.io/appicon-forge/)

## 许可证
Copyright © 2024-2025 HOE Team  

项目遵循[MIT许可证[↗]](https://github.com/GoldenHoe/MCSEasy/blob/main/LICENSE)

> [!NOTE]
> 这份许可证意味着：
> 
> 1.  **你可以随意使用这个项目代码**，无论是在个人项目还是商业项目中。
> 2.  **你可以修改并重新发布**这个代码。
> 3.  **你甚至可以用它来开发商业软件并销售**，只要你在你的产品中包含原始的 MIT 许可证文本和版权声明。
> 4.  **作者不提供任何保证**，如果使用该软件导致任何问题，你需要自己承担风险。

