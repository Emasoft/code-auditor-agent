defmodule UserService do
  use GenServer

  def handle_call({:list_all, []}, _from, state) do
    # Synchronous Repo.all on potentially huge table — blocks the
    # GenServer's scheduler for every other caller while it runs.
    users = Repo.all(User)
    {:reply, users, state}
  end

  def handle_call({:audit, user_id}, _from, state) do
    # Loads full audit log into memory (no Stream / no chunking).
    log = Repo.all(from a in AuditLog, where: a.user_id == ^user_id)
    {:reply, log, state}
  end
end
