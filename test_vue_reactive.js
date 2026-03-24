// 测试 Vue 3 响应式行为
const { ref, computed } = require('vue');

// 模拟状态
const imTestStatus = ref({
    dingtalk: { tested: false, passed: false }
});

// 模拟测试失败
console.log('=== 测试失败 ===');
imTestStatus.value.dingtalk = { tested: true, passed: false };
console.log('直接赋值后:', imTestStatus.value.dingtalk);

// 检查条件
const status = imTestStatus.value.dingtalk;
console.log('status.tested:', status.tested);
console.log('status.passed:', status.passed);
console.log('条件1 (passed && !edit):', status.passed && true);
console.log('条件2 (tested && !passed && !edit):', status.tested && !status.passed && true);

// 模拟展开运算符赋值
console.log('\n=== 使用展开运算符 ===');
imTestStatus.value = {
    ...imTestStatus.value,
    dingtalk: { tested: true, passed: false }
};
console.log('展开赋值后:', imTestStatus.value.dingtalk);

// 测试对象引用问题
console.log('\n=== 测试对象引用 ===');
const obj1 = { tested: true, passed: false };
imTestStatus.value.dingtalk = obj1;
console.log('赋值后:', imTestStatus.value.dingtalk);
console.log('相同引用?', imTestStatus.value.dingtalk === obj1);

obj1.passed = true;  // 修改原对象
console.log('修改原对象后:', imTestStatus.value.dingtalk);
console.log('居然变了! 这是引用问题');

