const sign_in_btn = document.querySelector("#sign-in-btn");
const sign_up_btn = document.querySelector("#sign-up-btn");
const container = document.querySelector(".container");

function showAdminLogin() {
  container.classList.add("admin-mode");
  container.classList.remove("sign-up-mode");
  document.querySelector('.admin-form-container').style.display = 'flex';
}

// Переключение панелей
sign_up_btn.addEventListener("click", () => {
  container.classList.add("sign-up-mode");
  container.classList.remove("admin-mode");
});

sign_in_btn.addEventListener("click", () => {
  container.classList.remove("sign-up-mode");
  container.classList.remove("admin-mode");
});

// Обработка формы входа
document.querySelector(".sign-in-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(e.target);
  const data = {
    username: formData.get("username"),
    password: formData.get("password"),
  };

  try {
    const response = await fetch("http://127.0.0.1:5000/api/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });
    const result = await response.json();
    const messageContainer = document.querySelector(".message-container"); // Add a container for messages
    messageContainer.textContent = ""; // Clear previous messages

    if (response.ok) {
      messageContainer.textContent = result.message; // Display success message
      messageContainer.style.color = "green"; // Set success message color
      setTimeout(() => {
        window.location.href = "/chat"; // Redirect to chat page
      }, 1000); // 2000 milliseconds = 2 seconds
    } else {
      messageContainer.textContent = result.error; // Display error message
      messageContainer.style.color = "red"; // Set error message color
    }
  } catch (error) {
    const messageContainer = document.querySelector(".message-container");
    messageContainer.textContent = "Ошибка сервера";
    messageContainer.style.color = "red";
  }
});

// Обработка формы регистрации
document.querySelector(".sign-up-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(e.target);
  const data = {
    username: formData.get("username"),
    email: formData.get("email"),
    password: formData.get("password"),
  };

  try {
    const response = await fetch("http://127.0.0.1:5000/api/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });
    const result = await response.json();
    if (response.ok) {
      alert(result.message);
      setTimeout(() => {
        window.location.href = "/chat"; // Redirect to chat page
      }, 1000); // 2000 milliseconds = 2 seconds
    } else {
      alert(result.error);
    }
  } catch (error) {
    alert("Ошибка сервера");
  }
});

// Обработка формы входа админа
document.querySelector(".admin-sign-in-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.querySelector(".admin-sign-in-form input[name='username']").value;
  const password = document.querySelector(".admin-sign-in-form input[name='password']").value;
  
  console.log("Отправка данных администратора:", { username, password });
  
  const data = {
    username: username,
    password: password
  };

  try {
    const response = await fetch("http://127.0.0.1:5000/api/admin/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(data),
      credentials: "include"  // Важно для сохранения сессии
    });
    
    console.log("Статус ответа:", response.status);
    const result = await response.json();
    console.log("Ответ сервера:", result);
    
    const messageContainer = document.querySelector(".admin-sign-in-form .message-container");
    messageContainer.textContent = "";

    if (response.ok) {
      messageContainer.textContent = result.message;
      messageContainer.style.color = "green";
      setTimeout(() => {
        window.location.href = "/admin"; // Redirect to admin page
      }, 1000);
    } else {
      messageContainer.textContent = result.error;
      messageContainer.style.color = "red";
    }
  } catch (error) {
    console.error("Ошибка:", error);
    const messageContainer = document.querySelector(".admin-sign-in-form .message-container");
    messageContainer.textContent = "Ошибка сервера";
    messageContainer.style.color = "red";
  }
});

document.addEventListener('DOMContentLoaded', function() {
    const signUpBtn = document.querySelector('.sign-up-btn');
    const signInBtn = document.querySelector('.sign-in-btn');
    const container = document.querySelector('.container');

    signUpBtn.addEventListener('click', () => {
        container.classList.add('sign-up-mode');
    });

    signInBtn.addEventListener('click', () => {
        container.classList.remove('sign-up-mode');
    });

    function showAdminLogin() {
        container.classList.add('admin-mode');
    }

    // Add event listener to admin button
    const adminBtn = document.querySelector('.admin-btn');
    if (adminBtn) {
        adminBtn.addEventListener('click', showAdminLogin);
    }

    // Handle admin login form submission
    const adminForm = document.querySelector('.admin-sign-in-form');
    if (adminForm) {
        adminForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = adminForm.querySelector('input[type="text"]').value;
            const password = adminForm.querySelector('input[type="password"]').value;

            try {
                const response = await fetch('/api/admin/login', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ username, password })
                });

                const data = await response.json();
                if (response.ok) {
                    window.location.href = '/admin';
                } else {
                    const messageContainer = adminForm.querySelector('.message-container');
                    if (messageContainer) {
                        messageContainer.textContent = data.error || 'Login failed';
                    }
                }
            } catch (error) {
                console.error('Error:', error);
            }
        });
    }
});