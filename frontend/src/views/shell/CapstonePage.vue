<script setup>
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  ApartmentOutlined,
  ArrowRightOutlined,
  CheckCircleFilled,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CodeOutlined,
  FileDoneOutlined,
  FileTextOutlined,
  FormOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  RightOutlined,
  SearchOutlined,
  TeamOutlined,
  WarningOutlined
} from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'

const { role } = useShellContext()
const previewRole = ref(role.value || 'STUDENT')
watch(role, value => { previewRole.value = value || 'STUDENT' })

const stages = [
  {
    key: 'requirements',
    label: '需求',
    title: '问题与需求',
    state: 'done',
    progress: 100,
    deadline: '第5周',
    summary: '明确工单处理的角色、业务范围和可验证需求。',
    deliverables: [
      { name: '问题与用户说明', meta: '2个目标角色 · 第2版', state: '已确认' },
      { name: '功能需求清单', meta: '8条需求 · 全部可验证', state: '已确认' },
      { name: '非功能需求', meta: '性能、安全、可用性', state: '已确认' }
    ]
  },
  {
    key: 'analysis',
    label: '分析',
    title: '业务分析',
    state: 'done',
    progress: 100,
    deadline: '第7周',
    summary: '分析工单生命周期、业务对象和关键规则。',
    deliverables: [
      { name: '工单状态模型', meta: '7个状态 · 12条流转规则', state: '已确认' },
      { name: '领域对象说明', meta: '工单、处理记录、维修人员', state: '已确认' },
      { name: '异常场景清单', meta: '5类异常情况', state: '已确认' }
    ]
  },
  {
    key: 'design',
    label: '设计',
    title: '模块设计',
    state: 'active',
    progress: 68,
    deadline: '本周五',
    summary: '把本周接口设计实验的方法应用到工单处理模块。',
    deliverables: [
      { name: '接口设计', meta: '4个接口 · 已关联需求', state: '已完成' },
      { name: '数据库设计', meta: '3张表 · 第3版', state: '修改中' },
      { name: '异常处理设计', meta: '尚未覆盖重新打开场景', state: '未开始' },
      { name: '设计检查单', meta: '已完成3/5项', state: '检查中' }
    ]
  },
  {
    key: 'implementation',
    label: '编码',
    title: '编码实现',
    state: 'upcoming',
    progress: 24,
    deadline: '第12周',
    summary: '实现模块核心流程，并持续关联需求和设计。',
    deliverables: [
      { name: '工单状态服务', meta: '基础结构已创建', state: '进行中' },
      { name: '处理记录接口', meta: '尚未开始', state: '未开始' },
      { name: '运行说明', meta: '尚未开始', state: '未开始' }
    ]
  },
  {
    key: 'testing',
    label: '测试',
    title: '测试与改进',
    state: 'upcoming',
    progress: 0,
    deadline: '第14周',
    summary: '验证业务规则，记录缺陷以及质量改进。',
    deliverables: [
      { name: '测试计划', meta: '尚未开始', state: '未开始' },
      { name: '测试用例', meta: '尚未开始', state: '未开始' },
      { name: '缺陷与修复记录', meta: '尚未开始', state: '未开始' }
    ]
  },
  {
    key: 'delivery',
    label: '交付',
    title: '交付与验收',
    state: 'locked',
    progress: 0,
    deadline: '第16周',
    summary: '提交可运行版本并完成个人模块验收。',
    deliverables: [
      { name: '可运行版本', meta: '等待前序阶段完成', state: '未开始' },
      { name: '使用说明', meta: '等待前序阶段完成', state: '未开始' },
      { name: '个人验收记录', meta: '尚未预约', state: '未开始' }
    ]
  }
]

const activeStageKey = ref('design')
const activeStage = computed(() => stages.find(item => item.key === activeStageKey.value) || stages[0])
const studentEvidence = [
  { requirement: 'REQ-06 接收工单', analysis: '工单状态模型', design: 'PUT /status', code: 'WorkOrderService', test: '待补充', state: 'warning' },
  { requirement: 'REQ-08 查看进度', analysis: '处理记录对象', design: 'GET /timeline', code: 'TimelineQuery', test: 'TEST-12', state: 'ready' },
  { requirement: 'REQ-09 取消工单', analysis: '取消业务规则', design: '待完善', code: '-', test: '-', state: 'missing' }
]
const topicMembers = [
  { name: '张明', module: '报修申请模块', stage: '编码', progress: 72 },
  { name: '李华', module: '工单处理模块', stage: '设计', progress: 58, current: true },
  { name: '王芳', module: '服务评价模块', stage: '分析', progress: 46 }
]

const teacherGroups = ref([
  {
    id: 'repair',
    name: '校园报修系统',
    description: '改善校内报修依赖电话和微信群、处理过程无法跟踪的问题。',
    status: 'APPROVED',
    statusLabel: '已通过',
    week: '第8周',
    riskCount: 1,
    modules: [
      { id: 'repair-apply', student: '张明', studentNo: '20240101', name: '报修申请模块', stage: '编码', progress: 72, risk: '正常', evidence: 14, lastUpdate: '今天 10:24' },
      { id: 'work-order', student: '李华', studentNo: '20240108', name: '工单处理模块', stage: '设计', progress: 58, risk: '设计逾期3天', evidence: 11, lastUpdate: '昨天 16:40' },
      { id: 'service-review', student: '王芳', studentNo: '20240116', name: '服务评价模块', stage: '分析', progress: 46, risk: '正常', evidence: 9, lastUpdate: '今天 09:12' }
    ]
  },
  {
    id: 'lab-assets',
    name: '实验室设备管理',
    description: '记录设备借用、巡检和异常处理过程，减少纸质登记。',
    status: 'PENDING',
    statusLabel: '待审批',
    week: '立项阶段',
    riskCount: 1,
    modules: [
      { id: 'asset-borrow', student: '陈晨', studentNo: '20240104', name: '设备借用模块', stage: '立项', progress: 12, risk: '正常', evidence: 3, lastUpdate: '今天 11:05' },
      { id: 'asset-inspection', student: '周宇', studentNo: '20240111', name: '设备巡检模块', stage: '立项', progress: 10, risk: '正常', evidence: 2, lastUpdate: '昨天 18:22' },
      { id: 'asset-alert', student: '林悦', studentNo: '20240123', name: '库存预警模块', stage: '立项', progress: 8, risk: '范围偏小', evidence: 2, lastUpdate: '3天前' }
    ]
  },
  {
    id: 'book-share',
    name: '校园图书共享',
    description: '支持闲置图书发布、预约借阅和归还追踪。',
    status: 'RETURNED',
    statusLabel: '修改中',
    week: '立项阶段',
    riskCount: 2,
    modules: [
      { id: 'book-publish', student: '刘洋', studentNo: '20240106', name: '图书发布模块', stage: '立项', progress: 9, risk: '边界重叠', evidence: 2, lastUpdate: '2天前' },
      { id: 'book-booking', student: '赵强', studentNo: '20240114', name: '预约借阅模块', stage: '立项', progress: 7, risk: '边界重叠', evidence: 2, lastUpdate: '2天前' },
      { id: 'book-return', student: '孙宁', studentNo: '20240125', name: '归还追踪模块', stage: '立项', progress: 11, risk: '正常', evidence: 3, lastUpdate: '今天 08:48' }
    ]
  }
])

const groupFilter = ref('ALL')
const groupQuery = ref('')
const selectedGroupId = ref('repair')
const selectedModuleId = ref('work-order')
const selectedGroup = computed(() => teacherGroups.value.find(item => item.id === selectedGroupId.value) || teacherGroups.value[0])
const selectedModule = computed(() => selectedGroup.value?.modules.find(item => item.id === selectedModuleId.value) || selectedGroup.value?.modules[0])
const visibleGroups = computed(() => teacherGroups.value.filter(item => {
  const matchesFilter = groupFilter.value === 'ALL' || item.status === groupFilter.value
  const query = groupQuery.value.trim().toLocaleLowerCase()
  const matchesQuery = !query || `${item.name} ${item.modules.map(module => `${module.student} ${module.name}`).join(' ')}`.toLocaleLowerCase().includes(query)
  return matchesFilter && matchesQuery
}))

const rubric = [
  { label: '问题与需求质量', score: 17, total: 20 },
  { label: '分析与设计合理性', score: 18, total: 20 },
  { label: '软件实现与可运行性', score: 16, total: 20 },
  { label: '测试和质量改进', score: 12, total: 15 },
  { label: '工程过程与成果一致性', score: 13, total: 15 },
  { label: '个人演示、验收和解释', score: 8, total: 10 }
]

function selectGroup(group) {
  selectedGroupId.value = group.id
  selectedModuleId.value = group.modules[0]?.id || ''
}

function approveTopic() {
  selectedGroup.value.status = 'APPROVED'
  selectedGroup.value.statusLabel = '已通过'
  message.success('已通过共同选题，个人模块仍可分别退回调整')
}

function returnTopic() {
  selectedGroup.value.status = 'RETURNED'
  selectedGroup.value.statusLabel = '修改中'
  message.info('已退回选题修改')
}

function prototypeAction(text) {
  message.success(text)
}
</script>

<template>
  <div class="capstone-page">
    <header class="page-title capstone-title">
      <div>
        <div class="eyebrow">贯穿16周的个人应用项目</div>
        <h1>{{ previewRole === 'STUDENT' ? '我的大作业' : '大作业管理' }}</h1>
        <p>{{ previewRole === 'STUDENT' ? '在共同选题中独立完成个人模块的需求、分析、设计、编码和测试。' : '审批共同选题和个人模块，跟踪每名学生的应用过程并独立验收。' }}</p>
      </div>
      <a-segmented
        v-model:value="previewRole"
        :options="[{label:'学生端',value:'STUDENT'},{label:'教师端',value:'TEACHER'}]"
      />
    </header>

    <template v-if="previewRole === 'STUDENT'">
      <section class="student-project-band">
        <div class="project-identity">
          <span class="project-mark"><ApartmentOutlined /></span>
          <div>
            <span class="section-kicker">共同选题 · 智慧服务组</span>
            <h2>校园报修系统</h2>
            <p>我的模块：<strong>工单处理模块</strong></p>
          </div>
        </div>
        <div class="project-facts">
          <div><span>立项状态</span><strong class="success"><CheckCircleOutlined /> 已通过</strong></div>
          <div><span>当前阶段</span><strong>设计</strong></div>
          <div><span>个人进度</span><strong>58%</strong></div>
          <div><span>阶段截止</span><strong>本周五</strong></div>
        </div>
      </section>

      <section class="class-transfer">
        <div class="transfer-copy">
          <span class="transfer-icon"><LinkOutlined /></span>
          <div>
            <span class="section-kicker">本周课堂迁移</span>
            <h2>把接口设计方法应用到自己的模块</h2>
            <p>为工单状态流转设计核心接口、输入输出和异常响应。</p>
          </div>
        </div>
        <div class="transfer-path" aria-label="从基本实验迁移到大作业">
          <div><small>基本实验07</small><strong>接口设计</strong><span><CheckCircleFilled /> 已完成</span></div>
          <ArrowRightOutlined />
          <div class="current"><small>个人应用任务</small><strong>工单状态接口</strong><span><ClockCircleOutlined /> 进行中</span></div>
        </div>
        <a-button type="primary" @click="activeStageKey='design'; prototypeAction('已定位到接口设计成果')">继续完成 <RightOutlined /></a-button>
      </section>

      <nav class="stage-rail" aria-label="大作业阶段">
        <button
          v-for="stage in stages"
          :key="stage.key"
          type="button"
          :class="['stage-step', stage.state, { active: activeStageKey === stage.key }]"
          @click="activeStageKey=stage.key"
        >
          <span class="stage-dot"><CheckCircleFilled v-if="stage.state==='done'" />{{ stage.state === 'done' ? '' : stages.indexOf(stage) + 1 }}</span>
          <span class="stage-label">{{ stage.label }}<small>{{ stage.state === 'done' ? '已确认' : `${stage.progress}%` }}</small></span>
        </button>
      </nav>

      <div class="student-workspace-grid">
        <main class="capstone-panel stage-workspace">
          <header class="panel-heading">
            <div>
              <span class="section-kicker">当前打开阶段</span>
              <h2>{{ activeStage.title }}</h2>
              <p>{{ activeStage.summary }}</p>
            </div>
            <div class="stage-deadline"><span>阶段截止</span><strong>{{ activeStage.deadline }}</strong></div>
          </header>

          <div class="deliverable-list">
            <button v-for="(item, index) in activeStage.deliverables" :key="item.name" type="button" @click="prototypeAction(`已打开“${item.name}”工作区`)">
              <span :class="['deliverable-index', {done:item.state==='已确认'||item.state==='已完成'}]">
                <CheckCircleOutlined v-if="item.state==='已确认'||item.state==='已完成'" />
                <FileTextOutlined v-else />
              </span>
              <span class="deliverable-name"><strong>{{ item.name }}</strong><small>{{ item.meta }}</small></span>
              <a-tag :color="item.state==='已确认'||item.state==='已完成'?'green':item.state==='未开始'?'default':'blue'">{{ item.state }}</a-tag>
              <RightOutlined />
            </button>
          </div>

          <footer class="stage-actions">
            <span>最近保存：今天 10:24 · 当前为个人草稿</span>
            <a-space>
              <a-button @click="prototypeAction('已保存新的个人版本')">保存新版本</a-button>
              <a-button type="primary" :disabled="activeStage.state==='locked'" @click="prototypeAction('阶段成果已提交教师检查')">提交阶段检查</a-button>
            </a-space>
          </footer>
        </main>

        <aside class="capstone-side">
          <section class="capstone-panel feedback-panel">
            <header><FormOutlined /><strong>教师反馈</strong><a-tag color="orange">1条待处理</a-tag></header>
            <p>工单状态需要补充“取消后重新打开”的处理规则，并同步检查接口异常响应。</p>
            <button type="button" @click="activeStageKey='design'">定位到相关成果 <RightOutlined /></button>
          </section>

          <section class="capstone-panel topic-members">
            <header><TeamOutlined /><strong>主题组模块</strong><span>共享题目，分别完成</span></header>
            <button v-for="member in topicMembers" :key="member.name" type="button" :class="{current:member.current}">
              <span class="member-avatar">{{ member.name.slice(0, 1) }}</span>
              <span><strong>{{ member.name }} · {{ member.module }}</strong><small>{{ member.stage }}阶段 · {{ member.progress }}%</small></span>
              <span v-if="member.current" class="mine">我的</span><RightOutlined v-else />
            </button>
          </section>
        </aside>
      </div>

      <section class="capstone-panel evidence-panel">
        <header class="panel-heading compact">
          <div><span class="section-kicker">个人成果一致性</span><h2>工程证据链</h2><p>每条需求都应能追踪到分析、设计、代码和测试。</p></div>
          <a-button @click="prototypeAction('已打开完整证据链')">查看全部</a-button>
        </header>
        <div class="evidence-table">
          <div class="evidence-head"><span>需求</span><span>分析</span><span>设计</span><span>代码</span><span>测试</span><span>状态</span></div>
          <button v-for="row in studentEvidence" :key="row.requirement" type="button">
            <span><strong>{{ row.requirement }}</strong></span><span>{{ row.analysis }}</span><span>{{ row.design }}</span><span>{{ row.code }}</span><span>{{ row.test }}</span>
            <span><a-tag :color="row.state==='ready'?'green':row.state==='warning'?'orange':'red'">{{ row.state==='ready'?'完整':row.state==='warning'?'待补测试':'缺少关联' }}</a-tag></span>
          </button>
        </div>
      </section>
    </template>

    <template v-else>
      <section class="teacher-metrics">
        <div><span class="metric-icon teal"><ApartmentOutlined /></span><p>主题组<strong>16</strong><small>组</small></p></div>
        <div><span class="metric-icon amber"><ClockCircleOutlined /></span><p>待审批<strong>3</strong><small>项</small></p></div>
        <div><span class="metric-icon red"><WarningOutlined /></span><p>风险模块<strong>5</strong><small>个</small></p></div>
        <div><span class="metric-icon green"><FileDoneOutlined /></span><p>待个人验收<strong>8</strong><small>人</small></p></div>
      </section>

      <section class="teaching-transfer capstone-panel">
        <div>
          <span class="section-kicker">第8周 · 教学推进</span>
          <h2>接口设计实验 → 个人模块接口设计</h2>
          <p>48名学生中，42人已完成基本实验，35人已进入大作业应用，21人已完成本周应用任务。</p>
        </div>
        <div class="transfer-stats">
          <div><span>基本实验</span><strong>42/48</strong></div>
          <ArrowRightOutlined />
          <div><span>进入应用</span><strong>35/48</strong></div>
          <ArrowRightOutlined />
          <div><span>完成应用</span><strong>21/48</strong></div>
        </div>
        <a-button @click="prototypeAction('已打开本周应用任务设置')">设置应用任务</a-button>
      </section>

      <div class="teacher-toolbar">
        <a-segmented v-model:value="groupFilter" :options="[{label:'全部主题',value:'ALL'},{label:'待审批',value:'PENDING'},{label:'已通过',value:'APPROVED'},{label:'修改中',value:'RETURNED'}]" />
        <a-input v-model:value="groupQuery" allow-clear placeholder="搜索主题、学生或个人模块"><template #prefix><SearchOutlined /></template></a-input>
      </div>

      <div class="teacher-workspace">
        <aside class="group-list capstone-panel">
          <header><strong>主题组</strong><span>{{ visibleGroups.length }}组</span></header>
          <button v-for="group in visibleGroups" :key="group.id" type="button" :class="{active:selectedGroupId===group.id}" @click="selectGroup(group)">
            <span class="group-list-main"><strong>{{ group.name }}</strong><small>{{ group.modules.map(item=>item.student).join('、') }}</small></span>
            <a-tag :color="group.status==='APPROVED'?'green':group.status==='PENDING'?'orange':'blue'">{{ group.statusLabel }}</a-tag>
            <span v-if="group.riskCount" class="risk-count"><WarningOutlined /> {{ group.riskCount }}</span>
          </button>
          <a-empty v-if="!visibleGroups.length" description="没有符合条件的主题组" />
        </aside>

        <main v-if="selectedGroup" class="group-detail capstone-panel">
          <header class="group-detail-heading">
            <div>
              <span class="section-kicker">共同选题</span>
              <h2>{{ selectedGroup.name }}</h2>
              <p>{{ selectedGroup.description }}</p>
            </div>
            <div class="topic-actions">
              <a-tag :color="selectedGroup.status==='APPROVED'?'green':selectedGroup.status==='PENDING'?'orange':'blue'">{{ selectedGroup.statusLabel }}</a-tag>
              <template v-if="selectedGroup.status==='PENDING'">
                <a-button @click="returnTopic">退回选题</a-button>
                <a-button type="primary" @click="approveTopic">通过共同选题</a-button>
              </template>
            </div>
          </header>

          <section class="module-section">
            <div class="section-heading"><div><h3>个人模块</h3><p>共同题目不计团队分，每个模块独立审批和验收。</p></div><span>{{ selectedGroup.modules.length }}人</span></div>
            <div class="module-table">
              <div class="module-head"><span>学生</span><span>个人模块</span><span>当前阶段</span><span>进度</span><span>风险</span><span></span></div>
              <button v-for="module in selectedGroup.modules" :key="module.id" type="button" :class="{active:selectedModuleId===module.id}" @click="selectedModuleId=module.id">
                <span><strong>{{ module.student }}</strong><small>{{ module.studentNo }}</small></span>
                <span><strong>{{ module.name }}</strong><small>{{ module.evidence }}项过程证据</small></span>
                <span>{{ module.stage }}</span>
                <span class="module-progress"><i><b :style="{width:`${module.progress}%`}"></b></i>{{ module.progress }}%</span>
                <span><a-tag :color="module.risk==='正常'?'green':'orange'">{{ module.risk }}</a-tag></span>
                <RightOutlined />
              </button>
            </div>
          </section>

          <section v-if="selectedModule" class="module-inspection">
            <header>
              <div><span class="section-kicker">个人过程检查</span><h3>{{ selectedModule.student }} · {{ selectedModule.name }}</h3><p>最近更新：{{ selectedModule.lastUpdate }}</p></div>
              <a-space><a-button @click="prototypeAction('已记录退回意见')">退回修改</a-button><a-button type="primary" @click="prototypeAction('该生当前阶段已通过')">通过当前阶段</a-button></a-space>
            </header>
            <div class="inspection-grid">
              <div class="inspection-chain">
                <h4>工程证据链</h4>
                <div><CheckCircleOutlined /><span><strong>需求</strong><small>8条需求，均可验证</small></span><b>完整</b></div>
                <div><CheckCircleOutlined /><span><strong>分析</strong><small>状态模型和业务规则已关联</small></span><b>完整</b></div>
                <div class="warning"><WarningOutlined /><span><strong>设计</strong><small>1条需求尚未关联接口设计</small></span><b>待补充</b></div>
                <div class="muted"><CodeOutlined /><span><strong>代码与测试</strong><small>将在后续阶段继续形成</small></span><b>未到阶段</b></div>
              </div>
              <div class="inspection-feedback">
                <h4>教师检查意见</h4>
                <a-textarea :rows="4" default-value="工单取消以后是否允许重新打开？请补充状态规则，并同步检查接口异常响应。" />
                <div><span>只反馈给该学生，不影响同主题组其他成员。</span><a-button @click="prototypeAction('检查意见已保存')">保存意见</a-button></div>
              </div>
            </div>
          </section>
        </main>
      </div>

      <section class="capstone-panel rubric-preview">
        <header class="panel-heading compact">
          <div><span class="section-kicker">第16周 · 个人验收</span><h2>个人评分单预览</h2><p>无团队分、无团队答辩，所有维度评价个人模块。</p></div>
          <strong class="rubric-total">84<small>/100</small></strong>
        </header>
        <div class="rubric-grid">
          <div v-for="item in rubric" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.score }}<small>/{{ item.total }}</small></strong><i><b :style="{width:`${item.score/item.total*100}%`}"></b></i></div>
        </div>
        <footer><span>抽查：REQ-08 → WorkOrderService → TEST-12</span><a-button type="primary" @click="prototypeAction('已打开个人验收评分')"><PlayCircleOutlined /> 开始个人验收</a-button></footer>
      </section>
    </template>
  </div>
</template>

<style scoped>
.capstone-page{padding:4px 0 40px;color:#293d48}.capstone-title{align-items:flex-end}.capstone-title>.ant-segmented{flex:0 0 auto}.section-kicker{display:block;margin-bottom:5px;color:#55717b;font-size:11px;font-weight:600}.capstone-panel{border:1px solid #dfe7ea;border-radius:7px;background:#fff}.student-project-band{display:grid;grid-template-columns:minmax(300px,1fr) auto;align-items:center;gap:32px;margin-bottom:16px;padding:22px 26px;border:1px solid #cfe0dd;background:#f8fbfa}.project-identity{display:flex;align-items:center;gap:15px;min-width:0}.project-mark{display:grid;width:48px;height:48px;place-items:center;flex:0 0 auto;border-radius:7px;background:#176b78;color:#fff;font-size:21px}.project-identity h2{margin:0;color:#20373f;font-size:21px}.project-identity p{margin:6px 0 0;color:#6d7f86;font-size:13px}.project-identity p strong{color:#2b464e}.project-facts{display:grid;grid-template-columns:repeat(4,minmax(78px,1fr));align-items:center}.project-facts>div{min-width:90px;padding:0 18px;border-left:1px solid #d9e5e3}.project-facts span,.project-facts strong{display:block}.project-facts span{color:#819097;font-size:10px}.project-facts strong{margin-top:5px;color:#304952;font-size:14px;white-space:nowrap}.project-facts strong.success{color:#28775d}.class-transfer{display:grid;grid-template-columns:minmax(280px,1fr) auto auto;align-items:center;gap:28px;margin-bottom:18px;padding:18px 22px;border-left:4px solid #d18b28;background:#fffaf1}.transfer-copy{display:flex;align-items:center;gap:13px;min-width:0}.transfer-icon{display:grid;width:38px;height:38px;place-items:center;flex:0 0 auto;border-radius:6px;background:#fff0d7;color:#ad6e17;font-size:17px}.transfer-copy h2,.teaching-transfer h2{margin:0;color:#3a4544;font-size:16px}.transfer-copy p,.teaching-transfer p{margin:5px 0 0;color:#7c7d75;font-size:12px}.transfer-path{display:flex;align-items:center;gap:13px}.transfer-path>div{min-width:132px}.transfer-path small,.transfer-path strong,.transfer-path span{display:block}.transfer-path small{color:#948c7b;font-size:10px}.transfer-path strong{margin:3px 0;color:#494a45;font-size:13px}.transfer-path span{color:#438367;font-size:10px}.transfer-path .current span{color:#b16d13}.transfer-path>.anticon{color:#b7a98d}.stage-rail{display:grid;grid-template-columns:repeat(6,1fr);margin:0 0 18px;border:1px solid #dfe7ea;background:#fff}.stage-step{position:relative;display:flex;align-items:center;justify-content:center;gap:9px;min-width:0;height:68px;padding:0 10px;border:0;border-right:1px solid #e6ecee;background:#fff;color:#718088;font:inherit;cursor:pointer}.stage-step:last-child{border-right:0}.stage-step:hover{background:#f7faf9}.stage-step.active{background:#eef7f5;color:#176b78;box-shadow:inset 0 -3px #176b78}.stage-step.done{color:#317a63}.stage-step.locked{color:#a4adb1}.stage-dot{display:grid;width:25px;height:25px;place-items:center;flex:0 0 auto;border:1px solid #bfcbd0;border-radius:50%;font-size:11px}.stage-step.done .stage-dot{border-color:#67a58e;background:#e8f5ef}.stage-step.active .stage-dot{border-color:#176b78;background:#176b78;color:#fff}.stage-label{min-width:0;font-size:13px;font-weight:600;text-align:left}.stage-label small{display:block;margin-top:2px;color:#94a0a5;font-size:9px;font-weight:400}.student-workspace-grid{display:grid;grid-template-columns:minmax(0,1fr) 330px;align-items:start;gap:18px}.panel-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;padding:21px 23px;border-bottom:1px solid #e7edef}.panel-heading h2,.group-detail-heading h2{margin:0;color:#263d47;font-size:19px}.panel-heading p,.group-detail-heading p{margin:5px 0 0;color:#788990;font-size:12px}.stage-deadline{text-align:right}.stage-deadline span,.stage-deadline strong{display:block}.stage-deadline span{color:#89969b;font-size:10px}.stage-deadline strong{margin-top:4px;color:#a86816;font-size:14px}.deliverable-list{padding:5px 18px}.deliverable-list>button{display:grid;grid-template-columns:34px minmax(0,1fr) auto 12px;align-items:center;gap:12px;width:100%;min-height:66px;padding:8px 6px;border:0;border-bottom:1px solid #edf1f2;background:#fff;color:inherit;font:inherit;text-align:left;cursor:pointer}.deliverable-list>button:last-child{border-bottom:0}.deliverable-list>button:hover{background:#f7faf9}.deliverable-index{display:grid;width:31px;height:31px;place-items:center;border-radius:6px;background:#f0f3f4;color:#72858d}.deliverable-index.done{background:#e9f5ef;color:#2c8062}.deliverable-name strong,.deliverable-name small{display:block}.deliverable-name strong{color:#344b55;font-size:13px}.deliverable-name small{margin-top:4px;color:#8a979c;font-size:10px}.deliverable-list>button>.anticon:last-child{color:#a2adb1;font-size:10px}.stage-actions{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:15px 23px;border-top:1px solid #e7edef;background:#fbfcfc}.stage-actions>span{color:#859398;font-size:10px}.capstone-side{display:grid;gap:18px}.feedback-panel{padding:17px 18px;border-left:3px solid #d18b28}.feedback-panel header,.topic-members header{display:flex;align-items:center;gap:8px;color:#344c55}.feedback-panel header>.ant-tag{margin-left:auto}.feedback-panel p{margin:14px 0;color:#5b686b;font-size:12px;line-height:1.75}.feedback-panel>button{padding:0;border:0;background:transparent;color:#a36718;font:inherit;font-size:11px;cursor:pointer}.topic-members{overflow:hidden}.topic-members header{padding:16px 17px;border-bottom:1px solid #e7edef}.topic-members header>span{margin-left:auto;color:#8b989d;font-size:9px}.topic-members>button{display:grid;grid-template-columns:32px minmax(0,1fr) auto;align-items:center;gap:10px;width:100%;min-height:64px;padding:8px 15px;border:0;border-bottom:1px solid #edf1f2;background:#fff;color:inherit;font:inherit;text-align:left;cursor:pointer}.topic-members>button:last-child{border-bottom:0}.topic-members>button:hover,.topic-members>button.current{background:#f3f8f7}.member-avatar{display:grid;width:30px;height:30px;place-items:center;border-radius:50%;background:#edf1f2;color:#61757d;font-size:11px}.topic-members button>span:nth-child(2) strong,.topic-members button>span:nth-child(2) small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.topic-members button>span:nth-child(2) strong{color:#3a5059;font-size:11px}.topic-members button>span:nth-child(2) small{margin-top:3px;color:#89979c;font-size:9px}.topic-members .mine{color:#23765e;font-size:10px}.topic-members button>.anticon{color:#a7b0b4;font-size:9px}.evidence-panel{margin-top:18px;overflow:hidden}.panel-heading.compact{align-items:center;padding:17px 22px}.evidence-table{overflow-x:auto}.evidence-head,.evidence-table>button{display:grid;grid-template-columns:1.25fr 1fr 1fr 1fr 1fr 74px;align-items:center;gap:14px;min-width:860px;padding:0 22px}.evidence-head{height:36px;color:#89979d;background:#f8fafb;font-size:9px}.evidence-table>button{width:100%;min-height:54px;border:0;border-top:1px solid #edf1f2;background:#fff;color:#5a6c73;font:inherit;font-size:11px;text-align:left;cursor:pointer}.evidence-table>button:hover{background:#f7faf9}.evidence-table>button strong{color:#354c55;font-size:11px}.teacher-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}.teacher-metrics>div{display:flex;align-items:center;gap:14px;min-height:92px;padding:16px 19px;border:1px solid #dfe7ea;background:#fff}.metric-icon{display:grid;width:38px;height:38px;place-items:center;border-radius:6px;font-size:17px}.metric-icon.teal{background:#e7f4f2;color:#176b78}.metric-icon.amber{background:#fff2dc;color:#ad6d15}.metric-icon.red{background:#fae9e7;color:#b6524b}.metric-icon.green{background:#eaf4e8;color:#4e8044}.teacher-metrics p{margin:0;color:#7b898f;font-size:11px}.teacher-metrics p strong{display:inline-block;margin:3px 4px 0 0;color:#2d434c;font-size:24px}.teacher-metrics p small{color:#89969b}.teaching-transfer{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:26px;margin-bottom:16px;padding:18px 21px}.transfer-stats{display:flex;align-items:center;gap:16px}.transfer-stats>div span,.transfer-stats>div strong{display:block}.transfer-stats>div span{color:#8a979c;font-size:9px}.transfer-stats>div strong{margin-top:3px;color:#304952;font-size:15px}.transfer-stats>.anticon{color:#9eb0b5}.teacher-toolbar{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:20px 0 12px}.teacher-toolbar>.ant-input-affix-wrapper{width:310px}.teacher-workspace{display:grid;grid-template-columns:290px minmax(0,1fr);align-items:start;gap:14px}.group-list{overflow:hidden}.group-list>header{display:flex;align-items:center;justify-content:space-between;height:48px;padding:0 16px;border-bottom:1px solid #e5ebed}.group-list>header strong{font-size:13px}.group-list>header span{color:#8d999e;font-size:10px}.group-list>button{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 8px;width:100%;min-height:76px;padding:12px 15px;border:0;border-bottom:1px solid #e9edef;background:#fff;color:inherit;font:inherit;text-align:left;cursor:pointer}.group-list>button:hover,.group-list>button.active{background:#f2f8f7}.group-list>button.active{box-shadow:inset 3px 0 #176b78}.group-list-main strong,.group-list-main small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.group-list-main strong{color:#344a54;font-size:12px}.group-list-main small{margin-top:5px;color:#87959a;font-size:9px}.risk-count{grid-column:1/-1;color:#b46f17;font-size:9px}.group-detail{min-width:0;overflow:hidden}.group-detail-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:20px 22px;border-bottom:1px solid #e5ebed}.group-detail-heading>div:first-child{max-width:700px}.topic-actions{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:8px}.module-section{padding:18px 22px}.section-heading{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px}.section-heading h3,.module-inspection h3{margin:0;color:#304750;font-size:15px}.section-heading p,.module-inspection header p{margin:4px 0 0;color:#849196;font-size:10px}.section-heading>span{color:#89969b;font-size:10px}.module-table{border:1px solid #e2e8ea}.module-head,.module-table>button{display:grid;grid-template-columns:110px minmax(150px,1fr) 72px 120px 104px 12px;align-items:center;gap:12px;padding:0 13px}.module-head{min-height:34px;color:#8b979c;background:#f8fafb;font-size:9px}.module-table>button{width:100%;min-height:62px;border:0;border-top:1px solid #e9edef;background:#fff;color:#607178;font:inherit;font-size:10px;text-align:left;cursor:pointer}.module-table>button:hover,.module-table>button.active{background:#f4f9f8}.module-table>button.active{box-shadow:inset 3px 0 #176b78}.module-table button span strong,.module-table button span small{display:block}.module-table button span strong{color:#354b54;font-size:11px}.module-table button span small{margin-top:3px;color:#8b979c;font-size:9px}.module-progress{display:flex;align-items:center;gap:7px}.module-progress i{display:block;width:62px;height:5px;overflow:hidden;background:#e4eaec}.module-progress i b{display:block;height:100%;background:#2b8073}.module-table>button>.anticon{color:#a0aaae;font-size:9px}.module-inspection{border-top:1px solid #e5ebed;background:#fbfcfc}.module-inspection>header{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:17px 22px}.inspection-grid{display:grid;grid-template-columns:minmax(300px,.9fr) minmax(320px,1.1fr);border-top:1px solid #e8edef}.inspection-chain,.inspection-feedback{padding:17px 22px}.inspection-chain{border-right:1px solid #e5ebed}.inspection-chain h4,.inspection-feedback h4{margin:0 0 12px;color:#4a5d65;font-size:11px}.inspection-chain>div{display:grid;grid-template-columns:18px minmax(0,1fr) auto;align-items:center;gap:9px;min-height:42px;border-bottom:1px solid #edf1f2;color:#2d8063}.inspection-chain>div:last-child{border-bottom:0}.inspection-chain>div.warning{color:#b06d17}.inspection-chain>div.muted{color:#8d999d}.inspection-chain span strong,.inspection-chain span small{display:block}.inspection-chain span strong{color:#3a5059;font-size:10px}.inspection-chain span small{margin-top:2px;color:#8a979c;font-size:8px}.inspection-chain b{font-size:9px;font-weight:500}.inspection-feedback>div{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:10px}.inspection-feedback>div span{color:#8b979c;font-size:9px}.rubric-preview{margin-top:16px;overflow:hidden}.rubric-total{color:#176b78;font-size:27px}.rubric-total small{color:#89969b;font-size:11px;font-weight:400}.rubric-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border-bottom:1px solid #e7edef}.rubric-grid>div{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:8px;padding:15px 20px;border-top:1px solid #edf1f2;border-right:1px solid #edf1f2}.rubric-grid>div:nth-child(3n){border-right:0}.rubric-grid span{color:#607279;font-size:10px}.rubric-grid strong{color:#304a53;font-size:16px}.rubric-grid strong small{color:#96a1a5;font-size:9px;font-weight:400}.rubric-grid i{grid-column:1/-1;display:block;height:4px;overflow:hidden;background:#e4eaec}.rubric-grid i b{display:block;height:100%;background:#39846f}.rubric-preview>footer{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:14px 20px}.rubric-preview>footer>span{color:#7f8e93;font-size:10px}
@media(max-width:1050px){.student-project-band{grid-template-columns:1fr}.project-facts>div:first-child{padding-left:0;border-left:0}.class-transfer,.teaching-transfer{grid-template-columns:1fr auto}.transfer-path,.transfer-stats{grid-column:1}.student-workspace-grid{grid-template-columns:minmax(0,1fr) 280px}.teacher-workspace{grid-template-columns:250px minmax(0,1fr)}.module-head,.module-table>button{grid-template-columns:88px minmax(130px,1fr) 62px 88px 90px 10px}.inspection-grid{grid-template-columns:1fr}.inspection-chain{border-right:0;border-bottom:1px solid #e5ebed}}
@media(max-width:760px){.capstone-title{align-items:stretch}.capstone-title>.ant-segmented{width:100%}.student-project-band{padding:18px}.project-facts{grid-template-columns:1fr 1fr;gap:14px}.project-facts>div{padding:0;border-left:0}.class-transfer,.teaching-transfer{display:flex;align-items:stretch;flex-direction:column}.transfer-path,.transfer-stats{width:100%;overflow-x:auto}.class-transfer>.ant-btn,.teaching-transfer>.ant-btn{width:100%}.stage-rail{grid-template-columns:repeat(6,92px);overflow-x:auto}.stage-step{height:62px}.student-workspace-grid{grid-template-columns:1fr}.panel-heading,.group-detail-heading,.module-inspection>header{align-items:stretch;flex-direction:column}.stage-actions{align-items:stretch;flex-direction:column}.stage-actions>.ant-space{display:grid!important;grid-template-columns:1fr 1fr}.stage-actions .ant-btn{width:100%}.teacher-metrics{grid-template-columns:1fr 1fr}.teacher-toolbar{align-items:stretch;flex-direction:column}.teacher-toolbar>.ant-input-affix-wrapper{width:100%}.teacher-workspace{grid-template-columns:1fr}.group-list{max-height:320px;overflow-y:auto}.module-table{overflow-x:auto}.module-head,.module-table>button{min-width:720px}.rubric-grid{grid-template-columns:1fr}.rubric-grid>div{border-right:0}.rubric-preview>footer{align-items:stretch;flex-direction:column}.evidence-panel{margin-right:0;margin-left:0}}
@media(max-width:480px){.teacher-metrics{grid-template-columns:1fr}.project-facts{grid-template-columns:1fr 1fr}.transfer-path>div{min-width:118px}.rubric-preview>footer .ant-btn{width:100%}}
</style>
