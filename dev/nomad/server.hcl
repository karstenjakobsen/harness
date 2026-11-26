name = "harness-dev-server"
data_dir = "/nomad/data"
bind_addr = "0.0.0.0"

ports {
  http = 14646
  rpc  = 14647
  serf = 14648
}

advertise {
  rpc  = "127.0.0.1:14647"
  # The single server uses its Serf address for Raft membership.
  serf = "127.0.0.1:14648"
}

server {
  enabled          = true
  bootstrap_expect = 1
}
