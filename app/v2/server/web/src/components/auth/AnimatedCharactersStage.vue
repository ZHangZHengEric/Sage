<template>
  <div class="characters-stage">
    <div class="stage-layer">
      <div class="stage-brand">
        <div class="stage-logo">
          <img :src="logoUrl" alt="Sage V2" class="stage-logo-image" />
        </div>
        <span>Sage V2</span>
      </div>
    </div>

    <div class="characters-frame">
      <div class="characters-canvas" style="width: 550px; height: 400px;">
        <div
          ref="purpleRef"
          class="character-body"
          :style="purpleBodyStyle"
        >
          <div class="character-eyes eyes-wide eyes-slow" :style="purpleEyesStyle">
            <EyeBall
              :size="18"
              :pupil-size="7"
              :max-distance="5"
              eye-color="white"
              pupil-color="#2D2D2D"
              :is-blinking="isPurpleBlinking"
              :force-look-x="purpleLookDirection.x"
              :force-look-y="purpleLookDirection.y"
            />
            <EyeBall
              :size="18"
              :pupil-size="7"
              :max-distance="5"
              eye-color="white"
              pupil-color="#2D2D2D"
              :is-blinking="isPurpleBlinking"
              :force-look-x="purpleLookDirection.x"
              :force-look-y="purpleLookDirection.y"
            />
          </div>
        </div>

        <div
          ref="blackRef"
          class="character-body"
          :style="blackBodyStyle"
        >
          <div class="character-eyes eyes-slow" :style="blackEyesStyle">
            <EyeBall
              :size="16"
              :pupil-size="6"
              :max-distance="4"
              eye-color="white"
              pupil-color="#2D2D2D"
              :is-blinking="isBlackBlinking"
              :force-look-x="blackLookDirection.x"
              :force-look-y="blackLookDirection.y"
            />
            <EyeBall
              :size="16"
              :pupil-size="6"
              :max-distance="4"
              eye-color="white"
              pupil-color="#2D2D2D"
              :is-blinking="isBlackBlinking"
              :force-look-x="blackLookDirection.x"
              :force-look-y="blackLookDirection.y"
            />
          </div>
        </div>

        <div
          ref="orangeRef"
          class="character-body"
          :style="orangeBodyStyle"
        >
          <div class="character-eyes eyes-wide" :style="orangeEyesStyle">
            <Pupil :size="12" :max-distance="5" pupil-color="#2D2D2D" :force-look-x="frontLookDirection.x" :force-look-y="frontLookDirection.y" />
            <Pupil :size="12" :max-distance="5" pupil-color="#2D2D2D" :force-look-x="frontLookDirection.x" :force-look-y="frontLookDirection.y" />
          </div>
        </div>

        <div
          ref="yellowRef"
          class="character-body"
          :style="yellowBodyStyle"
        >
          <div class="character-eyes" :style="yellowEyesStyle">
            <Pupil :size="12" :max-distance="5" pupil-color="#2D2D2D" :force-look-x="frontLookDirection.x" :force-look-y="frontLookDirection.y" />
            <Pupil :size="12" :max-distance="5" pupil-color="#2D2D2D" :force-look-x="frontLookDirection.x" :force-look-y="frontLookDirection.y" />
          </div>
          <div class="character-mouth" :style="yellowMouthStyle" />
        </div>
      </div>
    </div>

    <div class="stage-links">
      <a
        href="https://wiki.sage.zavixai.com/"
        target="_blank"
        rel="noreferrer"
        class="stage-link"
      >
        文档
      </a>
      <a
        href="https://github.com/ZHangZHengEric/Sage/blob/main/LICENSE"
        target="_blank"
        rel="noreferrer"
        class="stage-link"
      >
        MIT 许可
      </a>
      <a
        href="https://github.com/ZHangZHengEric/Sage/issues"
        target="_blank"
        rel="noreferrer"
        class="stage-link"
      >
        问题反馈
      </a>
    </div>

    <div class="stage-grid" />
    <div class="stage-glow glow-top" />
    <div class="stage-glow glow-bottom" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import EyeBall from './EyeBall.vue'
import Pupil from './Pupil.vue'

const logoUrl = '/sage_logo.svg'

const props = defineProps({
  isTyping: {
    type: Boolean,
    default: false
  },
  passwordLength: {
    type: Number,
    default: 0
  },
  showPassword: {
    type: Boolean,
    default: false
  }
})

const mouseX = ref(0)
const mouseY = ref(0)
const isPurpleBlinking = ref(false)
const isBlackBlinking = ref(false)
const isLookingAtEachOther = ref(false)
const isPurplePeeking = ref(false)
const purpleRef = ref(null)
const blackRef = ref(null)
const yellowRef = ref(null)
const orangeRef = ref(null)

const isPasswordHiddenTyping = computed(() => props.passwordLength > 0 && !props.showPassword)
const isPasswordVisible = computed(() => props.passwordLength > 0 && props.showPassword)

const handleMouseMove = (event) => {
  mouseX.value = event.clientX
  mouseY.value = event.clientY
}

const scheduleBlink = (targetRef) => {
  let blinkTimeout = null
  const run = () => {
    const delay = Math.random() * 4000 + 3000
    blinkTimeout = setTimeout(() => {
      targetRef.value = true
      blinkTimeout = setTimeout(() => {
        targetRef.value = false
        run()
      }, 150)
    }, delay)
  }
  run()
  return () => {
    if (blinkTimeout) clearTimeout(blinkTimeout)
  }
}

onMounted(() => {
  window.addEventListener('mousemove', handleMouseMove)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', handleMouseMove)
})

let stopPurpleBlink = () => {}
let stopBlackBlink = () => {}
onMounted(() => {
  stopPurpleBlink = scheduleBlink(isPurpleBlinking)
  stopBlackBlink = scheduleBlink(isBlackBlinking)
})

onUnmounted(() => {
  stopPurpleBlink()
  stopBlackBlink()
})

let lookTimer = null
watch(() => props.isTyping, (value) => {
  if (lookTimer) clearTimeout(lookTimer)
  if (value) {
    isLookingAtEachOther.value = true
    lookTimer = setTimeout(() => {
      isLookingAtEachOther.value = false
    }, 800)
  } else {
    isLookingAtEachOther.value = false
  }
})

onUnmounted(() => {
  if (lookTimer) clearTimeout(lookTimer)
})

let peekTimer = null
watch(
  () => [props.passwordLength, props.showPassword],
  ([passwordLength, showPassword]) => {
    if (peekTimer) clearTimeout(peekTimer)
    if (passwordLength > 0 && showPassword) {
      const delay = Math.random() * 3000 + 2000
      peekTimer = setTimeout(() => {
        isPurplePeeking.value = true
        peekTimer = setTimeout(() => {
          isPurplePeeking.value = false
        }, 800)
      }, delay)
    } else {
      isPurplePeeking.value = false
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  if (peekTimer) clearTimeout(peekTimer)
})

const calculatePosition = (elementRef) => {
  if (!elementRef.value) {
    return { faceX: 0, faceY: 0, bodySkew: 0 }
  }

  const rect = elementRef.value.getBoundingClientRect()
  const centerX = rect.left + rect.width / 2
  const centerY = rect.top + rect.height / 3
  const deltaX = mouseX.value - centerX
  const deltaY = mouseY.value - centerY

  return {
    faceX: Math.max(-15, Math.min(15, deltaX / 20)),
    faceY: Math.max(-10, Math.min(10, deltaY / 30)),
    bodySkew: Math.max(-6, Math.min(6, -deltaX / 120))
  }
}

const purplePos = computed(() => calculatePosition(purpleRef))
const blackPos = computed(() => calculatePosition(blackRef))
const yellowPos = computed(() => calculatePosition(yellowRef))
const orangePos = computed(() => calculatePosition(orangeRef))

const purpleLookDirection = computed(() => {
  if (isPasswordVisible.value) {
    return {
      x: isPurplePeeking.value ? 4 : -4,
      y: isPurplePeeking.value ? 5 : -4
    }
  }
  if (isLookingAtEachOther.value) {
    return { x: 3, y: 4 }
  }
  return { x: undefined, y: undefined }
})

const blackLookDirection = computed(() => {
  if (isPasswordVisible.value) {
    return { x: -4, y: -4 }
  }
  if (isLookingAtEachOther.value) {
    return { x: 0, y: -4 }
  }
  return { x: undefined, y: undefined }
})

const frontLookDirection = computed(() => {
  if (isPasswordVisible.value) {
    return { x: -5, y: -4 }
  }
  return { x: undefined, y: undefined }
})

const purpleBodyStyle = computed(() => ({
  left: '70px',
  width: '180px',
  height: props.isTyping || isPasswordHiddenTyping.value ? '440px' : '400px',
  backgroundColor: '#6C3FF5',
  borderRadius: '10px 10px 0 0',
  zIndex: 1,
  transform: isPasswordVisible.value
    ? 'skewX(0deg)'
    : props.isTyping || isPasswordHiddenTyping.value
      ? `skewX(${purplePos.value.bodySkew - 12}deg) translateX(40px)`
      : `skewX(${purplePos.value.bodySkew}deg)`,
  transformOrigin: 'bottom center'
}))

const purpleEyesStyle = computed(() => ({
  left: isPasswordVisible.value
    ? '20px'
    : isLookingAtEachOther.value
      ? '55px'
      : `${45 + purplePos.value.faceX}px`,
  top: isPasswordVisible.value
    ? '35px'
    : isLookingAtEachOther.value
      ? '65px'
      : `${40 + purplePos.value.faceY}px`,
}))

const blackBodyStyle = computed(() => ({
  left: '240px',
  width: '120px',
  height: '310px',
  backgroundColor: '#2D2D2D',
  borderRadius: '8px 8px 0 0',
  zIndex: 2,
  transform: isPasswordVisible.value
    ? 'skewX(0deg)'
    : isLookingAtEachOther.value
      ? `skewX(${blackPos.value.bodySkew * 1.5 + 10}deg) translateX(20px)`
      : props.isTyping || isPasswordHiddenTyping.value
        ? `skewX(${blackPos.value.bodySkew * 1.5}deg)`
        : `skewX(${blackPos.value.bodySkew}deg)`,
  transformOrigin: 'bottom center'
}))

const blackEyesStyle = computed(() => ({
  left: isPasswordVisible.value
    ? '10px'
    : isLookingAtEachOther.value
      ? '32px'
      : `${26 + blackPos.value.faceX}px`,
  top: isPasswordVisible.value
    ? '28px'
    : isLookingAtEachOther.value
      ? '12px'
      : `${32 + blackPos.value.faceY}px`,
}))

const orangeBodyStyle = computed(() => ({
  left: '0px',
  width: '240px',
  height: '200px',
  zIndex: 3,
  backgroundColor: '#FF9B6B',
  borderRadius: '120px 120px 0 0',
  transform: isPasswordVisible.value ? 'skewX(0deg)' : `skewX(${orangePos.value.bodySkew}deg)`,
  transformOrigin: 'bottom center'
}))

const orangeEyesStyle = computed(() => ({
  left: isPasswordVisible.value ? '50px' : `${82 + orangePos.value.faceX}px`,
  top: isPasswordVisible.value ? '85px' : `${90 + orangePos.value.faceY}px`,
}))

const yellowBodyStyle = computed(() => ({
  left: '310px',
  width: '140px',
  height: '230px',
  backgroundColor: '#E8D754',
  borderRadius: '70px 70px 0 0',
  zIndex: 4,
  transform: isPasswordVisible.value ? 'skewX(0deg)' : `skewX(${yellowPos.value.bodySkew}deg)`,
  transformOrigin: 'bottom center'
}))

const yellowEyesStyle = computed(() => ({
  left: isPasswordVisible.value ? '20px' : `${52 + yellowPos.value.faceX}px`,
  top: isPasswordVisible.value ? '35px' : `${40 + yellowPos.value.faceY}px`,
}))

const yellowMouthStyle = computed(() => ({
  left: isPasswordVisible.value ? '10px' : `${40 + yellowPos.value.faceX}px`,
  top: isPasswordVisible.value ? '88px' : `${88 + yellowPos.value.faceY}px`,
}))
</script>

<style scoped>
.characters-stage { position: relative; display: flex; flex-direction: column; justify-content: space-between; align-self: stretch; overflow: hidden; padding: 48px; color: var(--primary-foreground); background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 90%, white), var(--primary), color-mix(in srgb, var(--primary) 80%, white)); }
.stage-layer, .characters-frame, .stage-links { position: relative; z-index: 2; }
.stage-brand { display: flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 600; }
.stage-logo { width: 32px; height: 32px; border-radius: 8px; background: #ffffff1a; padding: 4px; }
.stage-logo-image { width: 100%; height: 100%; object-fit: contain; }
.characters-frame { display: flex; align-items: flex-end; justify-content: center; height: 500px; }
.characters-canvas { position: relative; flex-shrink: 0; }
.character-body { position: absolute; bottom: 0; transition: all 700ms ease-in-out; }
.character-eyes { position: absolute; display: flex; gap: 24px; transition: all 200ms ease-out; }
.eyes-wide { gap: 32px; }
.eyes-slow { transition: all 700ms ease-in-out; }
.character-mouth { position: absolute; width: 80px; height: 4px; background: #2d2d2d; border-radius: 999px; transition: all 200ms ease-out; }
.stage-links { display: flex; align-items: center; gap: 32px; font-size: 14px; color: #ffffff99; }
.stage-link { text-decoration: none; }
.stage-link:hover { color: var(--primary-foreground); }
.stage-grid { position: absolute; inset: 0; pointer-events: none; }
.stage-glow { position: absolute; border-radius: 50%; filter: blur(64px); pointer-events: none; }
.glow-top { top: 25%; right: 25%; width: 256px; height: 256px; background: #ffffff1a; }
.glow-bottom { bottom: 25%; left: 25%; width: 384px; height: 384px; background: #ffffff0d; }
@media (max-width: 1200px) { .characters-canvas { transform: scale(.82); transform-origin: center bottom; } .stage-links { gap: 16px; } }
@media (max-width: 1023px) { .characters-stage { display: none; } }
@media (prefers-reduced-motion: reduce) { .character-body, .character-eyes, .character-mouth { transition: none; } }
</style>
