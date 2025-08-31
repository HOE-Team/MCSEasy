# Minecraft 簡易開服程式 — MCSEasy

<p align="center">
  <img src="../logo.svg" alt="MCSEasy Logo" width="150">
</p>

<div align="center">
<p align="center">
  <b><a href=../README.md>简体中文</a> | <a>繁體中文</a> | <a href="README_ENG.md">English</a></b>
</p>

[![Stars](https://img.shields.io/github/stars/GoldenHoe/MCSEasy?style=for-the-badge&logo=data:image/svg%2bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZlcnNpb249IjEiIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiI+PHBhdGggZD0iTTggLjI1YS43NS43NSAwIDAgMSAuNjczLjQxOGwxLjg4MiAzLjgxNSA0LjIxLjYxMmEuNzUuNzUgMCAwIDEgLjQxNiAxLjI3OWwtMy4wNDYgMi45Ny43MTkgNC4xOTJhLjc1MS43NTEgMCAwIDEtMS4wODguNzkxTDggMTIuMzQ3bC0zLjc2NiAxLjk4YS43NS43NSAwIDAgMS0xLjA4OC0uNzlsLjcyLTQuMTk0TC44MTggNi4zNzRhLjc1Ljc1IDAgMCAxIC40MTYtMS4yOGw0LjIxLS42MTFMNy4zMjcuNjY4QS43NS43NSAwIDAgMSA4IC4yNVoiIGZpbGw9IiNlYWM1NGYiLz48L3N2Zz4=&logoSize=auto&label=Stars&labelColor=444444&color=eac54f)](https://github.com/GoldenHoe/MCSEasy)
[![LICENSE](https://img.shields.io/github/license/GoldenHoe/MCSEasy?style=for-the-badge)](https://github.com/GoldenHoe/MCSEasy/blob/main/LICENSE)
![GitHub Release](https://img.shields.io/github/v/release/GoldenHoe/MCSEasy?label=Release&logo=github&style=for-the-badge)
</div>

### 用於 *協助需要建立 Minecraft 伺服器的使用者啟動並監控其 MC 伺服器*

## 概述

本專案為一個**用於自動部署 Minecraft 伺服器的工具**，以 **Python** 編寫，並使用 **PyInstaller** 打包。
主要目標為**簡化伺服器的安裝與啟動流程，讓使用者更輕鬆地部署並監控他們的 Minecraft 伺服器狀態**。

## MCSEasy 的優勢

### ✨ 輕量化
體積小，無需安裝第三方應用程式；點擊即可執行。
<div align="center">
    <img src="../images/MXIntro.png" style="border-radius: 5px;" alt="MXIntro">
</div>

### ⭐ 快速管理
介面清晰，伺服器管理便利快速。
<div align="center">
    <img src="../images/UIIntro.png" width="75%" style="border-radius: 5px;" alt="UIIntro">
</div>

### 🛠️ 版本支援
MCSEasy 支援多種伺服器端下載；Forge 端的下載使用由 [BMCLAPI ↗](https://bmclapidoc.bangbang93.com/) 提供的高速來源。
<div align="center">
    <img src="../images/VSIntro.png" width="75%" style="border-radius: 5px;" alt="VSIntro">
</div>

> **注意**
> #### MCSEasy 1.2 支援下載的伺服器類型
> - Vanilla
> - Paper
> - Forge
> - Fabric

### 🎨 自訂化
提供基礎自訂功能以及可選的半透明視窗模式。
<div align="center">
    <img src="./images/GXHIntro.png" width="75%" style="border-radius: 5px;" alt="VSIntro">
</div>

## 使用說明

### 系統需求（必備）
1. 支援的 Windows 作業系統：
    > **支援的 Windows 版本：**
    > - Windows 7 (Service Pack 1/2) (Build 7601/7602)
    > - Windows Server 2008 R2 (Service Pack 1/2) (Build 7601/7602)
    > - Windows 8 (Build 9200)
    > - Windows Server 2012 (Build 9200)
    > - Windows 8.1 (Build 9600)
    > - Windows Server 2012 R2 (Build 9600)
    > - Windows 10
    > - Windows Server 2016/2019/2022 (Build 14393/17763/20348)
    > - Windows 11
    > - Windows Server 2025 (Build 26100)

    > **警告：**
    > 目前不支援 Linux 發行版。
2. 網路連線。

### 建議
1. Java Development Kit (JDK) 8 或 OpenJDK 8。
2. 足夠的硬碟空間以儲存 Minecraft 伺服器檔案。
3. CPU：建議 2 核心以上（最佳為 8 核心以上）。
4. 至少 2 GB 記憶體 (RAM)。
5. 使用 100 Mbps 或更高的乙太網路連接。
6. 如有需要，可使用 frp 等內網穿透工具（無需公共 IP）。
7. 安裝 Python 3.6 或更新版本。

## 下載方式

1. 從 GitHub 倉庫克隆本專案。
2. 下載釋出的壓縮包並解壓至指定資料夾。
3. 下載 Release 發布的可執行檔（已打包為 .exe）。

## 啟動

解壓後 **直接執行**： `MCSEasy-vx.x.x.x-<release-type>.exe`

### 發行版本說明（自 v1.2.0.0-Beta1 起實施）
- Beta（測試版，不穩定）
- RC（Release Candidate，發行候選版）
- GA（General Availability，正式發行）
- LTS（長期支援版本 — 只有一個 LTS 版本：`LTS Release-v1.0.0`；該版本自 2024 年 11 月 1 日後已不可用）
- EP（Emergency Patch，緊急修補版本）

```
# 版本號示例
MCSEasy <版本號>-<發行類型>

MCSEasy v1.2.0.0-Beta1 (測試版)
MCSEasy v1.2.0.0-RC1 (發行候選)
MCSEasy v1.2.0.0-RC1-GUIRefactor (帶說明後綴的 RC)
MCSEasy v1.2.0.0-GA (正式版)
```

## 注意事項

依據您的電腦效能與網路狀況，某些操作（下載與啟動）可能需要一些時間。

## *AI 內容說明

本專案部分 GUI 程式碼由 ChatGPT / Google Gemini 協助生成，後續已由人工審查與修改。  
AI 生成的內容用以提升開發效率，但不保證完全正確。專案維護與責任由開發者承擔。

## 貢獻與回饋

如發現任何問題或有建議，請發送郵件至 **hoe_team@outlook.com**。歡迎提交程式碼、文件或測試上的貢獻。
專案應用圖示由 [AppIcon Force ↗](https://zhangyu1818.github.io/appicon-forge/) 生成。

## 授權

Copyright © 2024–2025 HOE Team

本專案遵循 [MIT License ↗](https://github.com/GoldenHoe/MCSEasy/blob/main/LICENSE)。

> **備註** — 此授權代表：
> 1. **您可以自由使用此程式碼**，無論是個人或商業用途。
> 2. **您可以修改並重新散布** 程式碼。
> 3. **您可以使用此程式碼開發並銷售商業軟體**，但必須在產品中包含原始 MIT 授權文本與版權聲明。
> 4. **作者不提供任何保證**；若使用本軟體導致任何問題，需自行承擔風險。
