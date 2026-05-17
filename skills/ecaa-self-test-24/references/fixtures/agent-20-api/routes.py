# ruff: noqa
# Intentionally contains the bugs each detector should catch.
# REST verb misuse — single handler for GET / POST / PUT / DELETE.
# DELETE branch performs unauthenticated destructive removal.
@app.route("/api/users/<id>", methods=["GET", "POST", "PUT", "DELETE"])
def user_handler(id):
    if request.method == "DELETE":
        db.users.delete(id)
        return "", 204
    if request.method == "POST":
        db.users.create(request.json)
        return request.json
    return db.users.find(id)
