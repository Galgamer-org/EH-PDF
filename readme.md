# EH-PDF

將一個 E-Hentai 畫廊下載並轉換成 PDF，方便在 Kindle 上閱讀
以及在 iPad 上閱讀並作筆記，，，

Download manga from E-Hentai and export to PDF, for Kindle and iPad！

## 特色

https://user-images.githubusercontent.com/66236255/201678755-45cb9072-fa94-44fd-89d5-cd90d3367cfb.mp4


 * 支持將 E-Hentai 和 ExHentai 轉換成 PDF！
 * 支持登入加載和不登入加載（登入可以享受到你的帳號的特權，比如說加載大圖）
 * 多線程同時加載（很快！開得越多越快，默認 12 線程）
 * 將彩色頁面轉換成灰度並提高對比度（方便 Kindle 閱讀！）
 * 將頁面縮放到指定的尺寸（節約空間！）
 * 支持斷點續傳！下載失敗時，直接重新原地運行一遍，程序會從中斷的地方自動重啓
 * ...

## 安裝方法

### 免安裝學習版

https://github.com/Yamabuki-bakery/EH-PDF/releases

提供 64 位 Windows 和 Linux 版

### Python 版

你的電腦需要安裝 Python 3.8 以上版本才能運行。

克隆這個倉庫（或者 [🔗下載壓縮包](https://github.com/Yamabuki-bakery/EH-PDF/archive/refs/heads/master.zip)）：

```shell
git clone https://github.com/Yamabuki-bakery/EH-PDF
cd EH-PDF
```

安裝依賴庫：asyncio, aiohttp, pillow

```shell
pip3 install -r requirements.txt
```

...然後運行

```shell
python3 eh-pdf.py --help
```

## 使用方法

一鍵下載 https://exhentai.org/g/2339054/da04b84080/ 的畫廊爲 PDF：
```shell
python3 eh-pdf.py https://exhentai.org/g/2339054/da04b84080/
```

如果網絡中斷導致下載失敗，則把原命令再原樣運行一次即可，程序會在失敗的地方繼續運行，，，

參數說明：
 * -g 輸出 PDF 文件，否則僅下載圖片
 * -g 輸出灰度圖像 PDF，方便 Kindle 觀看並節省文件大小
 * -x <像素> 限制圖像的寬度 
 * -y <像素> 限制圖像的高度
 * -c <文件路徑> 你的 E-Hentai 登入 cookies，不指定默認讀取當前目錄 cookies.json
 * -o <文件路徑> 輸出 PDF 的文件，不指定默認在當前目錄下以本子標題生成一個 PDF
 * -d 在 log 上輸出羅嗦信息
 * -j <數量> 下載線程數，不指定就默認 32

命令行返回值

 * 0: 成功
 * 1: 網路故障
 * 其他：其他故障

