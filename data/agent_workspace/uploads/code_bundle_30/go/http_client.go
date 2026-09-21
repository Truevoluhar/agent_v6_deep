package main

import (
    "fmt"
    "net/http"
)

func status(url string) string {
    res, _ := http.Get(url)
    return fmt.Sprintf("%d", res.StatusCode)
}
