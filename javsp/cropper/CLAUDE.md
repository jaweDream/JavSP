[根目录](../../CLAUDE.md) > [javsp](../) > **cropper**

# Cropper 封面裁剪模块

## 变更记录 (Changelog)

| 时间 | 变更内容 |
|-----|---------|
| 2026-02-04T14:40:05 | 初始化模块文档 |

---

## 模块职责

`javsp/cropper/` 模块负责将横版封面（fanart）裁剪为竖版海报（poster），支持：
- 默认裁剪：从右侧裁剪指定比例
- AI 裁剪：使用 Slimeface 人脸识别定位演员位置进行智能裁剪

---

## 入口与启动

模块不独立启动，由主程序 `__main__.py` 中的 `process_poster()` 函数调用。

```python
from javsp.cropper import get_cropper, Cropper

# 获取裁剪器实例
cropper = get_cropper(engine)  # engine: SlimefaceEngine | None

# 执行裁剪
poster = cropper.crop(fanart_image, ratio=1.42)
```

---

## 对外接口

### 工厂函数 (`__init__.py`)

```python
def get_cropper(engine: SlimefaceEngine | None) -> Cropper:
    """根据配置获取对应的裁剪器实例

    Args:
        engine: 裁剪引擎配置，None 表示使用默认裁剪

    Returns:
        Cropper: 裁剪器实例
    """
```

### 裁剪器接口 (`interface.py`)

```python
from abc import ABC, abstractmethod
from PIL.Image import Image

class Cropper(ABC):
    @abstractmethod
    def crop_specific(self, fanart: Image, ratio: float) -> Image:
        """具体裁剪实现（子类重写）"""
        pass

    def crop(self, fanart: Image, ratio: float | None = None) -> Image:
        """裁剪入口，默认比例 1.42"""
        if ratio is None:
            ratio = 1.42
        return self.crop_specific(fanart, ratio)
```

### DefaultCropper (`interface.py`)

默认裁剪策略：从右侧裁剪，保持指定宽高比。

```python
class DefaultCropper(Cropper):
    def crop_specific(self, fanart: Image, ratio: float) -> Image:
        """从右侧裁剪为 poster 尺寸

        - 如果图片太"矮"：以高度为基准计算宽度
        - 如果图片太"瘦"：以宽度为基准计算高度
        """
```

### SlimefaceCropper (`slimeface_crop.py`)

使用 Slimeface 库进行人脸检测，智能定位裁剪区域。

```python
class SlimefaceCropper(Cropper):
    def crop_specific(self, fanart: Image, ratio: float) -> Image:
        """使用 AI 人脸识别进行智能裁剪"""
```

---

## 关键依赖与配置

### 依赖包

- `pillow`: 图片处理
- `slimeface`: AI 人脸检测（可选，需安装 `ai-crop` extra）

### 安装 AI 裁剪

```bash
poetry install --extras ai-crop
# 或
uv sync --extra ai-crop
```

### 配置项 (`config.yml`)

```yaml
summarizer:
  cover:
    crop:
      # 需要使用 AI 裁剪的番号模式（正则表达式）
      on_id_pattern:
        - '^\d{6}[-_]\d{3}$'   # 无码番号
        - '^ARA'               # 素人系列
        - '^SIRO'
        - '^GANA'
        - '^MIUM'
        - '^HHL'

      # 裁剪引擎配置
      engine: null  # null 表示禁用 AI 裁剪

      # 使用 Slimeface:
      # engine:
      #   name: slimeface
```

---

## 数据模型

### 输入
- `fanart`: PIL.Image 对象（横版封面）

### 输出
- `poster`: PIL.Image 对象（竖版海报，宽高比约 1:1.42）

### 裁剪比例

默认比例 `1.42`，即 `高度 / 宽度 = 1.42`，符合常见海报尺寸。

---

## 测试与质量

### 测试方法

```python
from PIL import Image
from javsp.cropper import get_cropper

# 测试默认裁剪
cropper = get_cropper(None)
fanart = Image.open('fanart.jpg')
poster = cropper.crop(fanart)
poster.save('poster.jpg')

# 测试 AI 裁剪
from javsp.config import SlimefaceEngine
engine = SlimefaceEngine(name='slimeface')
cropper = get_cropper(engine)
poster = cropper.crop(fanart)
```

---

## 常见问题 (FAQ)

### Q: 何时使用 AI 裁剪？

根据配置的 `on_id_pattern` 判断：
- 影片为无码（`movie.info.uncensored` 或 `movie.data_src == 'fc2'`）
- 番号匹配配置的正则模式

### Q: AI 裁剪失败怎么办？

AI 裁剪失败时会回退到默认裁剪（从右侧裁剪）。

### Q: 如何调整裁剪比例？

修改 `crop()` 调用时的 `ratio` 参数，或修改 `interface.py` 中的默认值 `1.42`。

---

## 相关文件清单

| 文件 | 说明 |
|-----|------|
| `__init__.py` | 模块入口，工厂函数 `get_cropper()` |
| `interface.py` | 抽象接口 `Cropper` 和默认实现 `DefaultCropper` |
| `slimeface_crop.py` | Slimeface AI 裁剪实现 |
| `utils.py` | 裁剪工具函数 |

---

*文档生成时间: 2026-02-04T14:40:05*
