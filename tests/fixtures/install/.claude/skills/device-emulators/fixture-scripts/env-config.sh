# Fixture env config for the device-emulators tests: env_config <env> <field>.
env_config() {
  case "$2" in
    app_identifier) echo "com.example.app.$1" ;;
    *) echo "env_config: unknown field $2" >&2; return 1 ;;
  esac
}
