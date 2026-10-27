import uvicorn

if __name__ == "__main__":
    uvicorn.run("fridge.server:app", host="127.0.0.1", port=7860, access_log=False)
