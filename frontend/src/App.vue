<template>
  <a-config-provider :theme="{ token: { colorPrimary: '#1769aa', borderRadius: 8, fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, Microsoft YaHei, sans-serif' } }">
    <router-view />
  </a-config-provider>
</template>
