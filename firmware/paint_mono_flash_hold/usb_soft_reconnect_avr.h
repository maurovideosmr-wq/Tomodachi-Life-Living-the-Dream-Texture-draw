/**
 * ATmega32U4（Leonardo / Pro Micro 等）：软件模拟「拔插 USB」。
 *
 * 背景：Arduino AVR 核心里 `USBDevice.detach()` 是空函数，不会真正从总线断开。
 * Switch 上首次枚举后常出现「要选手柄、第一次 L+R 无效，拔插后才正常」——与主机二次枚举有关。
 *
 * 做法：置位 `UDCON.DETACH` 断开上拉 → 等待 → `USBDevice.attach()` 全量恢复 USB。
 *
 * 调时间：在 #include 本文件**之前**可定义 USB_SOFT_RECONNECT_DETACHED_MS /
 * USB_SOFT_RECONNECT_AFTER_ATTACH_MS；关闭功能：`#define RUN_SWITCH_USB_BUS_SOFT_RECONNECT 0`。
 *
 * 与其它固件 sketch 目录内同文件保持同步。
 */
#pragma once

#include <Arduino.h>

#if defined(USBCON) && defined(UDCON) && defined(DETACH)

#ifndef RUN_SWITCH_USB_BUS_SOFT_RECONNECT
#define RUN_SWITCH_USB_BUS_SOFT_RECONNECT 1
#endif

// 原版：断开 1.5 秒 (1500)
#ifndef USB_SOFT_RECONNECT_DETACHED_MS
#define USB_SOFT_RECONNECT_DETACHED_MS 800  // 优化：800毫秒足够让 Switch 判定设备已拔出
#endif

// 原版：重连后等待 2.5 秒 (2500)
#ifndef USB_SOFT_RECONNECT_AFTER_ATTACH_MS
#define USB_SOFT_RECONNECT_AFTER_ATTACH_MS 1500  // 优化：1.5秒足够 Switch 重新识别 USB 设备
#endif

inline void UsbBusSoftReconnectAvr32u4() {
  UDCON |= (1 << DETACH);
  delay(USB_SOFT_RECONNECT_DETACHED_MS);
  USBDevice.attach();
  delay(USB_SOFT_RECONNECT_AFTER_ATTACH_MS);
}

#else

#ifndef RUN_SWITCH_USB_BUS_SOFT_RECONNECT
#define RUN_SWITCH_USB_BUS_SOFT_RECONNECT 0
#endif

inline void UsbBusSoftReconnectAvr32u4() {}

#endif
