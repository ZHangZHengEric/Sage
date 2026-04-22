"""
测试根说明（不修改 sys.path；由仓库根目录 pytest.ini 的 pythonpath = . 提供导入根）。

目录约定:
  - app/          服务端
  - common/       共享服务与模型
  - sagents/      与主包 sagents/ 同结构的单测
  - manual/       手跑脚本，pytest 不递归（见 pytest.ini norecursedirs）
"""
