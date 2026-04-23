/**
 * Switch 手柄烟测（NintendoSwitchControlLibrary）
 *
 * 上传后从 PC 拔掉，插入 Switch：在可接收输入的界面应约每 3 秒收到一次 A 键。
 * 用于确认 USB HID 与库工作正常，再开发贴图绘制自动化。
 *
 * 板型：库 README 仅保证 Arduino Leonardo。Pro Micro（ATmega32U4）多数可选用
 * 「Arduino Leonardo」或安装 SparkFun 板支持后选 「SparkFun Pro Micro」。
 *
 * Windows / Switch 若不识别为手柄，需将 Leonardo 的 USB VID/PID 改为 HORI/Pokken
 * 运行态（见 ../USB_VID_PID_patch.md）。
 *
 * 重要：库内 SwitchControlLibrary() 为「函数内 static」，第一次调用若晚于 USB 枚举，
 * Windows 只会出现串口、joy.cpl 无手柄。必须在 USBDevice.attach() 之前完成注册，
 * 故用全局对象的构造函数在 main() 之前调用 SwitchControlLibrary()。
 */
#include <NintendoSwitchControlLibrary.h>

namespace {
struct EarlySwitchHidRegister {
  EarlySwitchHidRegister() {
    (void)SwitchControlLibrary();
  }
} g_early_switch_hid;
}  // namespace

void setup() {
}

void loop() {
  delay(3000);
  pushButton(Button::A, 200);
}
