/**
 * Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
 *
 * Description: SLE multi-anchor ranging sample entry. \n
 *
 * History: \n
 * 2023-07-07, Create file. \n
 */
#include "soc_osal.h"
#include "common_def.h"
#include "app_init.h"
#include "sle_measure_dis_protocol.h"
#if defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_SERVER)
#include "sle_measure_dis_server.h"
#elif defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT)
#include "sle_measure_dis_client.h"
#endif

#define TASK_PRIORITY_HADM          27
#define MEASURE_DIS_VERSION         "0.1.0-alpha"
#define STACK_SIZE_BASELINE 0x200
#ifdef CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_SERVER
#define BTH_HADM_SERVICE_STACK_SIZE (STACK_SIZE_BASELINE * 4 + 0x1000)
#else
#define BTH_HADM_SERVICE_STACK_SIZE (STACK_SIZE_BASELINE * 4 + 0x200)
#endif

#if defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_SERVER)
/* Anchor 主任务：等待 IQ 队列事件并执行后续测距计算和数据转发。 */
void sle_measure_dis_server_task(void)
{
    uint32_t ret;
    ret = measure_dis_server_init();
    check_rc_return_rc(ret, "con sle_measure_dis_server_init");
    while (1) {
        ret = osal_event_read(
            &measure_dis_evt, MEASURE_DIS_MSG_EVENT,
            OSAL_WAIT_FOREVER, OSAL_WAITMODE_OR | OSAL_WAITMODE_CLR);

        sle_measure_dis_msg_proc();
    }
}
#elif defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT)
/* Client/Collector 主任务：初始化后周期推进扫描、连接和超时状态机。 */
void sle_measure_dis_client_task(void)
{
    uint32_t ret;
    ret = measure_dis_client_init();
    check_rc_return_rc(ret, "con sle_measure_dis_client_init");
    while (1) {
        measure_dis_client_periodic();
        osal_msleep(MEASURE_DIS_CLIENT_TASK_INTERVAL_MS);
    }
}
#endif

/* 示例统一入口：根据 Kconfig 选择角色并创建对应 RTOS 任务。 */
static void measure_dis_entry(void)
{
    osal_printk("SLE multi-anchor ranging %s, anchors:%u.\r\n",
                MEASURE_DIS_VERSION, MEASURE_DIS_MAX_ANCHORS);
    osal_task *task_handle = NULL;
    osal_kthread_lock();
#if defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_SERVER)
    task_handle = osal_kthread_create((osal_kthread_handler)sle_measure_dis_server_task,
                                      0, "SLEMeasureDisServer", BTH_HADM_SERVICE_STACK_SIZE);
#elif defined(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT)
    task_handle = osal_kthread_create((osal_kthread_handler)sle_measure_dis_client_task,
                                      0, "SLEMeasureDisClient", BTH_HADM_SERVICE_STACK_SIZE);
#endif
    if (task_handle != NULL) {
        osal_kthread_set_priority(task_handle, TASK_PRIORITY_HADM);
        osal_kfree(task_handle);
    }
    osal_kthread_unlock();
}

app_run(measure_dis_entry);
