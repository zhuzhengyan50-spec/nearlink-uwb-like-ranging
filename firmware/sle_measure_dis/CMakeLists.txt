#===============================================================================
# @brief    cmake file
# Copyright (c) HiSilicon (Shanghai) Technologies Co., Ltd. 2023-2023. All rights reserved.
#===============================================================================

# Enable Mode3 TOF fields in CS IQ report and ranging algorithm paths.
add_definitions(-DGLE_CS_MODE3_SUPPORT)

if(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_CLIENT)
    set(SOURCES_LIST
        ${CMAKE_CURRENT_SOURCE_DIR}/sle_measure_dis_client/sle_measure_dis_client.c
        ${CMAKE_CURRENT_SOURCE_DIR}/sle_measure_dis_client/sle_measure_dis_client_slem.c
        ${CMAKE_CURRENT_SOURCE_DIR}/sle_measure_dis.c
    )
    set(HEADER_LIST
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/sle_measure_dis_client
    )
elseif(CONFIG_SAMPLE_SUPPORT_SLE_MEASURE_DIS_SERVER)
    set(SOURCES_LIST
        ${CMAKE_CURRENT_SOURCE_DIR}/sle_measure_dis_server/sle_measure_dis_server.c
        ${CMAKE_CURRENT_SOURCE_DIR}/sle_measure_dis_server/sle_measure_dis_server_adv.c
        ${CMAKE_CURRENT_SOURCE_DIR}/sle_measure_dis_server/sle_measure_dis_server_alg.c
        ${CMAKE_CURRENT_SOURCE_DIR}/sle_measure_dis.c
    )
    set(HEADER_LIST
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/sle_measure_dis_server
    )
endif()

set(SOURCES "${SOURCES}" ${SOURCES_LIST} PARENT_SCOPE)
set(PUBLIC_HEADER "${PUBLIC_HEADER}" ${HEADER_LIST} PARENT_SCOPE)
