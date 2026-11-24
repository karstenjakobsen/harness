name = "harness-server"
data_dir = "/nomad/data"
bind_addr = "0.0.0.0"

server {
  enabled = true
  bootstrap_expect = 1
}

# The single host client reaches this address through the loopback-only published port.
advertise {
  rpc = "127.0.0.1:4647"
}

consul {
  auto_advertise = false
  server_auto_join = false
  client_auto_join = false
}
