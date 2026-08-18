const axios = require('axios');
(async () => {
  try {
    const res = await axios.post('http://localhost:8443/api/agent/confirm', {
      session_id: "test",
      token: "test",
      approve: true,
      employee_id: "test"
    }, {
      headers: { Authorization: "Bearer dummy" }
    });
    console.log("Success", res.data);
  } catch (e) {
    if (e.response) console.log("Error", e.response.status, JSON.stringify(e.response.data));
    else console.log(e);
  }
})();
