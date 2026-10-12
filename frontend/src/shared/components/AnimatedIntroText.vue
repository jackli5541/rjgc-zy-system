<script>
import { cloneVNode, Comment, defineComponent, Fragment, h, Text } from 'vue'

export default defineComponent({
  name: 'AnimatedIntroText',
  setup(_, { slots }) {
    return () => {
      const content = slots.default?.() || []
      const collectText = nodes => nodes.map(node => {
        if (node.type === Comment) return ''
        if (typeof node.children === 'string') return node.children
        return Array.isArray(node.children) ? collectText(node.children) : ''
      }).join('')
      const text = collectText(content)
      const length = Array.from(text).length
      const step = Math.min(24, 650 / Math.max(1, length))
      let index = 0
      const animate = nodes => nodes.map(node => {
        if (node.type === Text) {
          return h(Fragment, null, Array.from(String(node.children || '')).map(char => {
            const delay = 160 + index++ * step
            return h('span', { class: 'intro-character', style: { animationDelay: `${delay}ms` } }, char)
          }))
        }
        if (Array.isArray(node.children)) {
          const copy = cloneVNode(node)
          copy.children = animate(node.children)
          return copy
        }
        if (typeof node.type === 'string' && typeof node.children === 'string') {
          const copy = h(node.type, node.props, animate([h(Text, null, node.children)]))
          copy.scopeId = node.scopeId
          return copy
        }
        return node
      })
      return h('p', { class: 'animated-intro-text', 'aria-label': text }, [
        h('span', { 'aria-hidden': 'true' }, animate(content)),
      ])
    }
  },
})
</script>

<style scoped>
.intro-character {
  animation: intro-character-reveal 1ms linear both;
}
@keyframes intro-character-reveal {
  from { visibility: hidden }
  to { visibility: visible }
}
@media (prefers-reduced-motion: reduce) {
  .intro-character { animation: none }
}
</style>
