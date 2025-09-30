import nonebot
from nonebot.adapters.milky import Adapter as NONEBOT_ADAPTER_MILKYAdapter

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(NONEBOT_ADAPTER_MILKYAdapter)


nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    if driver.env == "prod":
        from contextlib import suppress

        from nonebot_plugin_orm.__main__ import main

        with suppress(SystemExit):
            main(["upgrade"])

    nonebot.run()
