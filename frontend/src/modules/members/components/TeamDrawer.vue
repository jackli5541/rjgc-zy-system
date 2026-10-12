<script setup>
import { DownloadOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../../shellContext'
import TeamPortfolioCard from './TeamPortfolioCard.vue'

const { closeTeamDrawer, downloadTeamCoursework, exportingTeamIds, role, selectedTeam, startTeamDrawerResize, teamPortfolioInline, teamDrawerResizing, teamDrawerWidth } = useShellContext()
</script>

<template>
    <a-drawer v-if="role==='TEACHER'" :open="Boolean(selectedTeam)&&!teamPortfolioInline" title="小组档案" :mask="false" :width="`${teamDrawerWidth}px`" :get-container="false" :root-style="{position:'fixed','--drawer-width':`${teamDrawerWidth}px`}" :z-index="950" :push="false" :root-class-name="teamDrawerResizing?'team-portfolio-drawer resizing':'team-portfolio-drawer'" placement="right" @close="closeTeamDrawer">
      <span class="drawer-resize-handle" role="separator" aria-label="调整小组档案抽屉宽度" aria-orientation="vertical" @pointerdown="startTeamDrawerResize($event)"/>
      <template #extra><a-button class="team-export-button" v-if="role==='TEACHER'&&selectedTeam" :loading="exportingTeamIds.has(selectedTeam.id)" @click="downloadTeamCoursework(selectedTeam)"><DownloadOutlined/> 导出 ZIP</a-button></template>
      <TeamPortfolioCard/>
    </a-drawer>
</template>
