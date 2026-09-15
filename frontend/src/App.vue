<template>
  <a-config-provider :locale="zhCN" :theme="{ token: { colorPrimary: '#1769aa', borderRadius: 8, fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, Microsoft YaHei, sans-serif' } }">
    <router-view />
  </a-config-provider>
</template>

<script setup>
import zhCN from 'ant-design-vue/es/locale/zh_CN'
</script>
