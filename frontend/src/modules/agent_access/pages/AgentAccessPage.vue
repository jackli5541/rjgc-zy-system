<script setup>
import { computed } from 'vue'
import AnimatedIntroText from '../../../shared/components/AnimatedIntroText.vue'
import { useShellContext } from '../../../shellContext'
import { AGENT_SCOPE_LABELS } from '../composables/useAgentAccess'
const {
  agentTokens, agentCalls, agentTab, agentTokenModal, agentTokenForm, agentCreatedToken, agentGuideOpen, agentEndpoint,
  agentScopeOptions, agentClassOptions, loading, formatTime, openAgentTokenForm, saveAgentToken, revokeAgentToken, copyAgentText,
  agentConfigExample, agentPromptExample, session,
  agentImport, loadAgentImportAssignments, downloadAgentImportTemplate, pickAgentImportFile, previewAgentImport, confirmAgentImport,
} = useShellContext()
const rowStatus = { OK: { color: 'green', text: '可导入' }, ERROR: { color: 'red', text: '有问题' }, SKIPPED: { color: 'default', text: '已跳过' } }
const overwriteRows = computed(() => (agentImport.report?.grades || []).filter(item => item.status === 'OK' && item.needs_overwrite))
const feedbackProblems = computed(() => (agentImport.report?.feedbacks || []).filter(item => item.status === 'ERROR'))
const importable = computed(() => (agentImport.report?.summary.ok || 0) > 0)
const statusMeta = { ACTIVE: { color: 'green', text: '有效' }, EXPIRED: { color: 'orange', text: '已过期' }, REVOKED: { color: 'default', text: '已吊销' } }
function classNames(ids) { return ids.length ? ids.map(id => session.classes.find(item => item.id === id)?.name || '已删除班级').join('、') : '我的全部教学班' }
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">智能批改</div><h1>Agent 接入</h1><AnimatedIntroText>让 WorkBuddy 等 MCP 客户端读取作业、评分标准和互评，辅助批改。令牌只读，不能修改任何成绩，最终结果由你审核后导入。</AnimatedIntroText></div></div>
  <a-tabs v-model:active-key="agentTab">
    <a-tab-pane key="tokens" tab="接入令牌">
      <div class="agent-toolbar">
        <span>接入地址</span><code class="agent-endpoint">{{ agentEndpoint }}</code>
        <a-button @click="copyAgentText(agentEndpoint)">复制</a-button>
        <span class="agent-spacer"></span>
        <a-button type="primary" @click="openAgentTokenForm()">新建令牌</a-button>
      </div>
      <a-table :data-source="agentTokens" :loading="loading" :scroll="{ x: 1000 }" :pagination="false" row-key="id">
        <a-table-column title="名称" data-index="name" :width="160" />
        <a-table-column title="前缀" :width="120"><template #default="{ record }"><code>{{ record.prefix }}</code></template></a-table-column>
        <a-table-column title="权限范围" :width="180"><template #default="{ record }"><a-tag v-for="scope in record.scopes" :key="scope">{{ AGENT_SCOPE_LABELS[scope] || scope }}</a-tag></template></a-table-column>
        <a-table-column title="班级范围" :width="180"><template #default="{ record }">{{ classNames(record.class_ids) }}</template></a-table-column>
        <a-table-column title="学生姓名" :width="90"><template #default="{ record }">{{ record.expose_real_name ? '真实姓名' : '仅代号' }}</template></a-table-column>
        <a-table-column title="有效期至" :width="150"><template #default="{ record }">{{ formatTime(record.expires_at) }}</template></a-table-column>
        <a-table-column title="最近使用" :width="150"><template #default="{ record }">{{ record.last_used_at ? formatTime(record.last_used_at) : '无调用' }}</template></a-table-column>
        <a-table-column title="近 7 天" :width="130"><template #default="{ record }">{{ record.calls_7d }} 次<span v-if="record.failed_7d" class="agent-failed"> · 失败 {{ record.failed_7d }}</span></template></a-table-column>
        <a-table-column title="状态" :width="90"><template #default="{ record }"><a-tag :color="statusMeta[record.status]?.color">{{ statusMeta[record.status]?.text || record.status }}</a-tag></template></a-table-column>
        <a-table-column title="操作" :width="200" fixed="right"><template #default="{ record }">
          <a-space>
            <a @click="agentGuideOpen = true">接入说明</a>
            <a v-if="record.status !== 'REVOKED'" @click="openAgentTokenForm(record)">编辑</a>
            <a-popconfirm v-if="record.status !== 'REVOKED'" title="吊销后该令牌立即失效，确定吗？" ok-text="吊销" cancel-text="取消" @confirm="revokeAgentToken(record)"><a class="agent-danger">吊销</a></a-popconfirm>
          </a-space>
        </template></a-table-column>
        <template #emptyText><a-empty description="还没有令牌，点击“新建令牌”开始"/></template>
      </a-table>
    </a-tab-pane>
    <a-tab-pane key="import" tab="导入批改结果">
      <a-alert type="info" show-icon class="agent-gap-bottom" message="先下载模板交给 Agent 填写，审核修改后在这里上传。预览确认前不会改动任何成绩。" />
      <div class="agent-toolbar">
        <a-select :value="agentImport.classId" :options="agentClassOptions" placeholder="选择教学班" style="min-width: 220px" @change="loadAgentImportAssignments" />
        <a-select v-model:value="agentImport.assignmentId" :options="agentImport.assignments" placeholder="选择个人作业" :loading="agentImport.loadingAssignments" :not-found-content="agentImport.classId ? '该班级暂无已发布的个人作业' : '请先选择教学班'" style="min-width: 240px" />
        <a-button :disabled="!agentImport.assignmentId" @click="downloadAgentImportTemplate">下载模板</a-button>
        <a-upload :before-upload="pickAgentImportFile" :show-upload-list="false" accept=".xlsx,.xlsm"><a-button :disabled="!agentImport.assignmentId">{{ agentImport.file ? agentImport.file.name : '选择 Excel' }}</a-button></a-upload>
        <a-button type="primary" :loading="agentImport.loading" :disabled="!agentImport.file" @click="previewAgentImport">上传并预览</a-button>
      </div>
      <template v-if="agentImport.report">
        <a-space wrap class="agent-gap-bottom">
          <a-tag color="green">可导入 {{ agentImport.report.summary.ok }}</a-tag>
          <a-tag color="red">有问题 {{ agentImport.report.summary.error }}</a-tag>
          <a-tag>已跳过 {{ agentImport.report.summary.skipped }}</a-tag>
          <a-tag color="orange">将覆盖网页 AI 草稿 {{ agentImport.report.summary.ai_draft }}</a-tag>
          <a-tag color="orange">已有教师评价 {{ agentImport.report.summary.needs_overwrite }}</a-tag>
          <a-tag>二次点评 {{ agentImport.report.summary.feedback_ok }}</a-tag>
        </a-space>
        <a-table :data-source="agentImport.report.grades" :pagination="{ pageSize: 20, showSizeChanger: false }" :scroll="{ x: 900 }" row-key="row" size="small">
          <a-table-column title="行" data-index="row" :width="60" />
          <a-table-column title="学号" data-index="student_no" :width="120" />
          <a-table-column title="姓名" data-index="name" :width="100" />
          <a-table-column title="等级" data-index="grade" :width="70" />
          <a-table-column title="作业点评" data-index="comment" :ellipsis="true" />
          <a-table-column title="二次点评" data-index="feedback_count" :width="90" />
          <a-table-column title="状态" :width="260"><template #default="{ record }">
            <a-tag :color="rowStatus[record.status].color">{{ rowStatus[record.status].text }}</a-tag>
            <a-tag v-if="record.ai_draft" color="orange">将覆盖网页 AI 草稿</a-tag>
            <a-tag v-if="record.needs_overwrite" color="orange">已有评价（{{ record.existing_grade }}）</a-tag>
            <div v-for="text in record.errors" :key="text" class="agent-failed">{{ text }}</div>
          </template></a-table-column>
        </a-table>
        <div v-if="feedbackProblems.length" class="agent-gap"><strong>二次点评中的问题</strong>
          <div v-for="item in feedbackProblems" :key="item.row" class="agent-failed">第 {{ item.row }} 行：{{ item.errors.join('；') }}</div>
        </div>
        <div v-if="overwriteRows.length" class="agent-gap">
          <strong>以下学生已有教师评价，勾选后才会覆盖：</strong>
          <a-checkbox-group v-model:value="agentImport.overwrite" class="agent-overwrite">
            <a-checkbox v-for="item in overwriteRows" :key="item.version_id" :value="item.version_id">{{ item.student_no }} {{ item.name }}（原 {{ item.existing_grade }} → {{ item.grade }}）</a-checkbox>
          </a-checkbox-group>
        </div>
        <a-popconfirm v-if="importable" title="确认导入？教师评分和二次点评将立即对学生可见。" ok-text="确认导入" cancel-text="取消" @confirm="confirmAgentImport">
          <a-button type="primary" class="agent-gap" :loading="agentImport.loading">确认导入 {{ agentImport.report.summary.ok }} 人</a-button>
        </a-popconfirm>
      </template>
      <template v-if="agentImport.result">
        <a-result status="success" :title="`已导入 ${agentImport.result.summary.imported} 人`" :sub-title="`失败 ${agentImport.result.summary.failed}，跳过 ${agentImport.result.summary.skipped}`" />
        <div v-for="item in [...agentImport.result.failed, ...agentImport.result.skipped]" :key="`${item.row}-${item.reason}`" class="agent-hint">第 {{ item.row }} 行 {{ item.student_no }} {{ item.name }}：{{ item.reason }}</div>
      </template>
    </a-tab-pane>
    <a-tab-pane key="calls" tab="调用记录">
      <a-table :data-source="agentCalls" :loading="loading" :scroll="{ x: 800 }" :pagination="{ pageSize: 20, showSizeChanger: false }" row-key="id">
        <a-table-column title="时间" :width="170"><template #default="{ record }">{{ formatTime(record.created_at) }}</template></a-table-column>
        <a-table-column title="令牌" data-index="token_name" :width="150" />
        <a-table-column title="工具" data-index="tool" :width="180" />
        <a-table-column title="结果" :width="100"><template #default="{ record }"><a-tag :color="record.status === 'OK' ? 'green' : 'red'">{{ record.status === 'OK' ? '成功' : '失败' }}</a-tag></template></a-table-column>
        <a-table-column title="错误码" :width="160"><template #default="{ record }">{{ record.error_code || '-' }}</template></a-table-column>
        <a-table-column title="耗时" :width="90"><template #default="{ record }">{{ record.latency_ms }} ms</template></a-table-column>
        <a-table-column title="IP" :width="140"><template #default="{ record }">{{ record.ip_address || '-' }}</template></a-table-column>
        <template #emptyText><a-empty description="暂无调用记录"/></template>
      </a-table>
    </a-tab-pane>
  </a-tabs>

  <a-modal v-model:open="agentTokenModal.open" :title="agentTokenModal.editing ? '编辑令牌' : '新建令牌'" ok-text="保存" cancel-text="取消" @ok="saveAgentToken">
    <a-form layout="vertical">
      <a-form-item label="名称"><a-input v-model:value="agentTokenForm.name" :maxlength="80" placeholder="例如：WorkBuddy 批改" /></a-form-item>
      <a-form-item label="权限范围"><a-checkbox-group v-model:value="agentTokenForm.scopes" :options="agentScopeOptions" /></a-form-item>
      <a-form-item label="班级范围（不选 = 我的全部教学班）"><a-select v-model:value="agentTokenForm.class_ids" mode="multiple" :options="agentClassOptions" placeholder="全部教学班" allow-clear /></a-form-item>
      <a-form-item label="向 Agent 提供学生真实姓名"><a-switch v-model:checked="agentTokenForm.expose_real_name" /><div class="agent-hint">关闭后只提供代号。学生作业会发送给客户端所用的外部模型，请确认符合你所在学校的数据规定。</div></a-form-item>
      <a-form-item v-if="!agentTokenModal.editing" label="有效天数"><a-input-number v-model:value="agentTokenForm.expires_days" :min="1" :max="365" /></a-form-item>
      <a-form-item v-else label="续期"><a-checkbox v-model:checked="agentTokenForm.renew">从今天起重新计算有效期</a-checkbox> <a-input-number v-if="agentTokenForm.renew" v-model:value="agentTokenForm.expires_days" :min="1" :max="365" /></a-form-item>
    </a-form>
  </a-modal>

  <a-modal :open="Boolean(agentCreatedToken)" title="令牌已创建" :footer="null" :closable="false" :mask-closable="false" width="640px">
    <a-alert type="warning" show-icon message="令牌只显示这一次，关闭后无法再次查看。请立即复制并配置到客户端。" />
    <pre class="agent-code">{{ agentCreatedToken }}</pre>
    <a-space><a-button type="primary" @click="copyAgentText(agentCreatedToken, '令牌已复制')">复制令牌</a-button><a-button @click="copyAgentText(agentConfigExample(agentCreatedToken), '配置已复制')">复制含令牌的配置</a-button><a-button @click="agentCreatedToken = ''">我已保存，关闭</a-button></a-space>
  </a-modal>

  <a-modal v-model:open="agentGuideOpen" title="接入说明" :footer="null" width="720px">
    <p>1. 在 WorkBuddy 的 MCP 设置中添加远程服务（Streamable HTTP），地址和请求头如下。字段名称以客户端实际界面为准。</p>
    <pre class="agent-code">{{ agentConfigExample() }}</pre>
    <a-button @click="copyAgentText(agentConfigExample(), '配置已复制')">复制配置</a-button>
    <p class="agent-gap">2. 令牌只能通过 HTTPS 访问；吊销或过期后立即失效。</p>
    <p>3. 对话中可以这样开始批改：</p>
    <pre class="agent-code">{{ agentPromptExample }}</pre>
    <a-button @click="copyAgentText(agentPromptExample, '提示词已复制')">复制提示词</a-button>
    <p class="agent-gap">4. Agent 只能读取，不能写成绩。可用工具：check_connection、get_workflow_guide、list_assignments、get_grading_context、claim_next_submission、read_submission_file、release_claim、get_progress。</p>
  </a-modal>
</template>
