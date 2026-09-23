<script setup>
import { RightOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../../shellContext'

const { changePassword, formatTime, modals, noticesOpen, notifications, openNotification, passwordForm, readAll } = useShellContext()
</script>

<template>
    <a-modal v-model:open="noticesOpen" title="站内通知" :footer="null" width="520px" centered><div class="notification-toolbar"><span>{{notifications.filter(x=>!x.read).length ? `${notifications.filter(x=>!x.read).length} 条未读消息` : '消息已全部阅读'}}</span><a-button v-if="notifications.some(x=>!x.read)" type="link" @click="readAll">全部标为已读</a-button></div><a-empty v-if="!notifications.length" description="暂无通知"/><div v-else class="notification-list"><div v-for="item in notifications" :key="item.id" class="notification-item" :class="{unread:!item.read,actionable:item.link}" @click="openNotification(item)"><span class="notification-dot"/><div><strong>{{item.title}}</strong><span>{{formatTime(item.created_at)}}</span></div><RightOutlined v-if="item.link" class="notification-link-icon"/></div></div></a-modal>

    <a-modal v-model:open="modals.password" title="修改密码" @ok="changePassword"><a-form layout="vertical"><a-form-item label="当前密码"><a-input-password v-model:value="passwordForm.current_password"/></a-form-item><a-form-item label="新密码"><a-input-password v-model:value="passwordForm.new_password"/></a-form-item></a-form></a-modal>
</template>
