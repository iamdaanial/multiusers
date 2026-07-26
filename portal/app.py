from flask import Flask, render_template, request, redirect
from provision import provision_tenant, deprovision_tenant, load_tenants, update_storage

app = Flask(__name__)
tenants = load_tenants()


@app.route("/")
def home():
    return render_template("index.html", tenants=tenants)


@app.route("/add", methods=["POST"])
def add_tenant():
    name = request.form["name"]
    storage = request.form["storage"]
    password = request.form["password"]

    if not name.isalnum():
        return "Tenant name must be letters/numbers only", 400

    port = 9201 + len(tenants)
    provision_tenant(name, port, password, storage)

    tenants.append((name, storage, port))
    return redirect("/")


@app.route("/edit/<name>", methods=["POST"])
def edit_tenant(name):
    storage = request.form["storage"]

    port = None
    for t in tenants:
        if t[0] == name:
            port = t[2]

    update_storage(name, port, storage)

    for i in range(len(tenants)):
        if tenants[i][0] == name:
            tenants[i] = (name, storage, port)

    return redirect("/")


@app.route("/delete/<name>", methods=["POST"])
def delete_tenant(name):
    deprovision_tenant(name)
    tenants[:] = [t for t in tenants if t[0] != name]
    return redirect("/")


app.run(debug=True)
