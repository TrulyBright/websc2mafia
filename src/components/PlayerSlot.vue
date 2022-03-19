<script setup>
import DocumentationIcon from './icons/IconDocumentation.vue';
</script>
<script>
export default {
    props: [
        'index',
        'profile-image',
        'username',
        'role',
        'alive',
    ]
}
</script>
<template>
    <div class="player">
        <i>
            <slot name="profile">
                <DocumentationIcon></DocumentationIcon>
            </slot>
        </i>
        <div class="details">
            <h3>
                <slot name="username">{{username}}</slot>
            </h3>
            <slot name="role">{{role}}</slot>
        </div>
    </div>
</template>

<style scoped>
.player {

}
i {
    display: flex;
    place-items: center;
    place-content: center;
    width: 64px;
    height: 64px;
}
.details {
    display: flex;
    flex-direction: column;
}
h3 {
    font-size: 1.2rem;
    margin-bottom: 0.4rem;
}
</style>