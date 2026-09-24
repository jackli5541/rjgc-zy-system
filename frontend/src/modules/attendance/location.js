export function currentLocation(radiusMeters) {
  if (!navigator.geolocation) return Promise.reject(new Error('当前浏览器不支持定位'))
  if (!window.isSecureContext) return Promise.reject(new Error('定位需要 HTTPS，请通过安全连接访问系统'))
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      position => {
        if (position.coords.accuracy > Math.min(100, radiusMeters / 2)) {
          reject(new Error('定位精度不足，请开启精确定位后重试'))
          return
        }
        resolve({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy_meters: position.coords.accuracy
        })
      },
      error => {
        const reasons = {
          1: '请允许浏览器获取位置后重试',
          2: '暂时无法获取位置，请检查设备定位设置',
          3: '定位超时，请重试'
        }
        reject(new Error(reasons[error.code] || '定位失败，请重试'))
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 }
    )
  })
}
