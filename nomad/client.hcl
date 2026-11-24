name = "harness-client"
data_dir = "/var/lib/harness-nomad"
bind_addr = "127.0.0.1"

ports {
  http = 5646
  rpc  = 5647
  serf = 5648
}

advertise {
  http = "127.0.0.1:5646"
  rpc  = "127.0.0.1:5647"
  serf = "127.0.0.1:5648"
}

client {
  enabled = true
  servers = ["127.0.0.1:4647"]
  options = {
    "driver.allowlist" = "docker"
  }
}

plugin "docker" {
  config {
    # Compose owns the local worker image and reuses it across test runs.
    gc {
      image = false
    }
  }
}

consul {
  auto_advertise = false
  server_auto_join = false
  client_auto_join = false
}
