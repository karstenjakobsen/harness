bind_addr = "127.0.0.1"

advertise {
  http = "127.0.0.1:14649"
  rpc  = "127.0.0.1:14650"
  serf = "127.0.0.1:14651"
}

ports {
  http = 14649
  rpc  = 14650
  serf = 14651
}

client {
  enabled = true
  servers = ["127.0.0.1:14647"]
  options = {
    "driver.allowlist" = "docker"
  }
}
