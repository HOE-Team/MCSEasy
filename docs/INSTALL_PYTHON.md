# 在Linux上安装Python3和需要的外部库

> [!NOTE]
> macOS和某些Linux发行版已经安装了标准Python，但如果您的macOS/Linux预装的Python版本过旧（如Python 2.7），建议您更新到Python 3.10以上

## 1. 安装Python3
### Linux
> [!IMPORTANT]
> 我们**不建议**您使用非标准Linux环境（如proot）运行我们的程序

> #### 若包管理器使用dpkg  
> 在终端输入：
> ```bash
> sudo apt-get install python
> ```
> #### 若包管理器使用pacman
> 在终端输入：
> ```bash
> sudo pacman -Sy python3
> ```

> [!NOTE]
> #### 使用其他包管理器的请查阅发行版的官方文档进行安装
安装完成后验证安装
```bash
python --version
```
您应该能看到刚安装的最新版本号。


### macOS
> [!WARNING]
> 请勿随意更改或删除系统自带的 Python
> - 不要尝试卸载系统自带的 Python。
> - 不要尝试使用 sudo 强行升级系统自带的 Python。
> - 不要随意修改 /usr/bin 目录下的 python 或 python3 链接。

您可以直接从 Python 官网下载官方安装程序。

1. 下载安装程序 访问 Python 官方网站下载页面：https://www.python.org/downloads/macos/ 下载标有“Latest Python 3 Release” 的 macOS 安装器 (.pkg 文件)。

2. 运行安装 双击下载的.pkg 文件，并按照图形化安装向导的提示进行操作。

3. 验证安装 安装完成后，打开终端并运行：

```bash
python3 --version
```

您应该能看到刚安装的最新版本号。

注意： 官方安装包会将 Python 安装到 /Library/Frameworks/Python.framework/ 目录下，不会影响系统自带的 Python。

## 2. 安装项目使用的外部库
使用pip安装需要的包
```bash
python -m pip install pyqt5 psutil
```
输入`python`进入Python用`import`函数尝试导入来验证是否安装成功，无报错即安装完成
```bash
$ python
Python 3.12.11 (main, Jun  9 2025, 15:36:10) 
Type "help", "copyright", "credits" or "license" for more information.
>>> import psutil,PyQt5
>>>
```
