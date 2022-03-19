<script setup>
import PlayerSlot from './PlayerSlot.vue';
</script>
<script>
export default {
    data() {
        return {
            players: [
                {index: 1, username: 'test', role: '용두', alive: true}
            ]
        }
    }
}
</script>

<template>
    <PlayerSlot
        v-for="player in players"
        :key="player.index"
    />
</template>